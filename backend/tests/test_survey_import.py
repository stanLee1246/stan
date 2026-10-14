import base64
import csv
import io
import json
import zipfile
from xml.sax.saxutils import escape

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import IngestionBatch
from app.interest_models import InterestResponse
from app.interests import INSTRUMENT_VERSION, QUESTION_IDS

HEADERS = ['答卷编号', '同意授权', *QUESTION_IDS, '姓名', '提交时间']


def csv_file(rows=None, encoding='utf-8-sig'):
    buffer = io.StringIO(newline='')
    csv.writer(buffer).writerows([HEADERS, *(rows or [valid_row()])])
    return {'filename': '问卷导出.csv', 'content_base64': base64.b64encode(buffer.getvalue().encode(encoding)).decode()}


def valid_row(key='row_001', consent='是', first='5'):
    return [key, consent, first, *['3'] * 29, 'PRIVATE-STUDENT-NAME', '2026-10-14']


def payload(file=None, **changes):
    return {**(file or csv_file()), 'source_name': '问卷平台测试导出', 'data_kind': 'demo',
            'instrument_version': INSTRUMENT_VERSION, 'instrument_confirmed': True,
            'field_mapping': {'response_id': '答卷编号', 'consent': '同意授权', **{q: q for q in QUESTION_IDS}},
            'ignore_columns': ['提交时间'], **changes}


def count_batches():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(IngestionBatch))


def xlsx_file(formula=False):
    headers = ['答卷编号', '同意授权', *QUESTION_IDS]
    rows = [headers, valid_row()[:-2]]
    def column(n):
        text = ''
        while n:
            n, rem = divmod(n-1,26); text = chr(65+rem) + text
        return text
    xml_rows = []
    for i, row in enumerate(rows, 1):
        cells = []
        for j, value in enumerate(row, 1):
            f = '<f>1+1</f>' if formula and i == 2 and j == 3 else ''
            cells.append(f'<c r="{column(j)}{i}" t="inlineStr">{f}<is><t>{escape(value)}</t></is></c>')
        xml_rows.append(f'<row r="{i}">{"".join(cells)}</row>')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="答卷" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(xml_rows)+'</sheetData></worksheet>')
    return {'filename': '腾讯导出.xlsx', 'content_base64': base64.b64encode(stream.getvalue()).decode()}


def test_file_inspection_requires_admin_and_hides_raw_personal_data(client, student, admin):
    file = csv_file()
    assert client.post('/api/admin/surveys/file/inspect', json=file).status_code == 401
    assert client.post('/api/admin/surveys/file/inspect', headers=student, json=file).status_code == 403
    result = client.post('/api/admin/surveys/file/inspect', headers=admin, json=file)
    assert result.status_code == 200
    assert result.json()['removed_personal_columns'] == 1
    assert '姓名' not in result.json()['columns'] and 'PRIVATE-' not in result.text
    assert count_batches() == 0


@pytest.mark.parametrize('encoding', ['utf-8-sig','gb18030'])
def test_preview_is_readonly_then_commit_cleans_and_deduplicates(client, admin, encoding):
    data = payload(csv_file([valid_row(), valid_row(key='denied', consent='否'), valid_row(key='bad', first='9')], encoding))
    result = client.post('/api/admin/surveys/preview', headers=admin, json=data)
    assert result.status_code == 200, result.text
    preview = result.json()
    assert (preview['quality']['accepted'], preview['quality']['rejected']) == (1,2)
    assert 'PRIVATE-' not in result.text and count_batches() == 0
    commit = client.post('/api/admin/surveys/commit', headers=admin, json={**data, 'preview_fingerprint': preview['preview_fingerprint']})
    assert commit.status_code == 200, commit.text
    assert commit.json()['quality']['accepted'] == 1 and commit.json()['quality']['rejected'] == 2
    with SessionLocal() as db:
        response = db.scalar(select(InterestResponse))
        assert response.owner_user_id is None and response.response_key.startswith('export_')
        assert response.normalized_record['answers']['R1'] == 5
        raw = db.scalar(select(IngestionBatch.raw_content))
        assert all(text not in raw for text in ['PRIVATE-', 'denied', '姓名'])
    again = client.post('/api/admin/surveys/preview', headers=admin, json=data).json()
    assert again['quality']['duplicates'] == 1 and again['quality']['accepted'] == 0


def test_real_import_requires_both_authorizations_and_same_instrument(client, admin):
    assert client.post('/api/admin/surveys/preview', headers=admin, json=payload(data_kind='authorized')).status_code == 422
    assert client.post('/api/admin/surveys/preview', headers=admin, json=payload(instrument_confirmed=False)).status_code == 422
    assert client.post('/api/admin/surveys/preview', headers=admin, json=payload(instrument_version='other')).status_code == 422
    data = payload(csv_file([valid_row(consent='否')]),data_kind='authorized',authorized_consent=True)
    response = client.post('/api/admin/surveys/preview', headers=admin, json=data)
    assert response.status_code == 200 and response.json()['quality']['rejected'] == 1
    assert count_batches() == 0


def test_mapping_changes_require_new_preview_and_missing_items_rejected(client, admin):
    data = payload()
    preview = client.post('/api/admin/surveys/preview', headers=admin, json=data).json()
    changed = {**data, 'source_name': '另一个来源', 'preview_fingerprint': preview['preview_fingerprint']}
    assert client.post('/api/admin/surveys/commit', headers=admin, json=changed).status_code == 409
    wrong = csv_file()
    raw = base64.b64decode(wrong['content_base64']).decode('utf-8-sig').replace('C5','未对应题目',1)
    wrong['content_base64'] = base64.b64encode(raw.encode()).decode()
    mapping = {k:v for k,v in data['field_mapping'].items() if k != 'C5'}
    assert client.post('/api/admin/surveys/preview', headers=admin,json=payload(wrong,field_mapping=mapping,ignore_columns=['提交时间','未对应题目'])).status_code == 422
    assert count_batches() == 0


def test_xlsx_parse_preview_commit_and_formula_rejection(client, admin):
    file = xlsx_file()
    inspection = client.post('/api/admin/surveys/file/inspect', headers=admin,json=file)
    assert inspection.status_code == 200 and inspection.json()['record_count'] == 1
    data = payload(file,ignore_columns=[])
    preview = client.post('/api/admin/surveys/preview', headers=admin,json=data)
    assert preview.status_code == 200 and preview.json()['quality']['accepted'] == 1
    commit = client.post('/api/admin/surveys/commit',headers=admin,json={**data,'preview_fingerprint':preview.json()['preview_fingerprint']})
    assert commit.status_code == 200
    assert client.post('/api/admin/surveys/file/inspect',headers=admin,json=xlsx_file(formula=True)).status_code == 422


@pytest.mark.parametrize('file', [
    {'filename':'file.xls','content_base64':base64.b64encode(b'xls').decode()},
    {'filename':'file.xlsx','content_base64':base64.b64encode(b'not a ZIP').decode()},
    {'filename':'file.csv','content_base64':'@@@'},
    {'filename':'file.csv','content_base64':base64.b64encode(b'"broken,header\nrow').decode()},
])
def test_corrupted_or_unsupported_files_are_validation_errors(client, admin, file):
    assert client.post('/api/admin/surveys/file/inspect',headers=admin,json=file).status_code == 422


def test_xlsx_expansion_limit_and_formula_like_values_never_persist(client, admin):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('xl/workbook.xml','x'*5_000_001)
    assert client.post('/api/admin/surveys/file/inspect',headers=admin,json={'filename':'bomb.xlsx','content_base64':base64.b64encode(buf.getvalue()).decode()}).status_code == 413
    data=payload(csv_file([valid_row(first='=2+3')]))
    response=client.post('/api/admin/surveys/preview',headers=admin,json=data)
    assert response.status_code == 200 and response.json()['quality']['rejected'] == 1
    assert count_batches() == 0
