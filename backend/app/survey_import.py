"""Bounded local-file questionnaire import with a read-only preflight.

No upload or preview is persisted. Only the existing, consent-first importer
may retain validated whitelisted records after an explicit commit.
"""
import base64
import binascii
import csv
import hashlib
import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select

from .auth import administrator
from .database import get_db
from .interest_models import InterestResponse
from .interests import (CSV_OPTIONAL, CSV_REQUIRED, EXPORT_ALIASES, INSTRUMENT_VERSION,
                        QUESTION_IDS, SurveyCSVImport, SurveyImport, canonical_json,
                        export_column_mapping, import_surveys, normalize_external_record,
                        personal_column, record_hash, score_answers)

router = APIRouter(prefix='/api/admin/surveys', tags=['survey-import'])
MAX_FILE_BYTES = 1_000_000
MAX_CSV_BYTES = 500_000
MAX_EXPANDED_BYTES = 5_000_000
MAX_ROWS = 1000
MAX_COLUMNS = 100
XLSX_NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
SCALE_LABELS = {'很不喜欢': '1', '不太喜欢': '2', '一般': '3', '比较喜欢': '4', '很喜欢': '5'}


class FileInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=1_333_336)


class ImportInput(FileInput):
    source_name: str = Field(min_length=2, max_length=120)
    data_kind: Literal['demo', 'authorized'] = 'demo'
    authorized_consent: StrictBool = False
    instrument_version: str = Field(max_length=40)
    instrument_confirmed: StrictBool = False
    field_mapping: dict[str, str] = Field(default_factory=dict, max_length=38)
    ignore_columns: list[str] = Field(default_factory=list, max_length=100)


class CommitInput(ImportInput):
    preview_fingerprint: str = Field(min_length=64, max_length=64)


@dataclass
class ParsedExport:
    headers: list[str]
    rows: list[list[str]]
    format: str
    encoding: str
    source_hash: str
    sheet_count: int = 1


def fail(message, code=422):
    raise HTTPException(code, message)


def sensitive_header(header):
    return personal_column(header) or bool(re.search(r'\S+@\S+|(?<!\d)1[3-9]\d{9}(?!\d)', header))


def safe_xml(raw):
    # ElementTree does not fetch external entities; explicitly reject DTDs and
    # entity declarations as well, including their UTF-16 spelling.
    if re.search(br'<!\s*(?:DOCTYPE|ENTITY)', raw.replace(b'\0', b''), re.I):
        fail('Excel 包含不支持的 XML 声明，请重新导出为纯数据工作簿')
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        fail('Excel 内部数据损坏，请重新导出 XLSX 或 CSV')


def xlsx_rows(raw):
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        fail('这不是有效的 XLSX 文件；旧版 XLS 请另存为 XLSX 或 CSV')
    with archive:
        members = archive.infolist()
        if len(members) > 100 or len({m.filename for m in members}) != len(members):
            fail('Excel 内部文件过多或重复，请只保留待导入的数据表')
        if sum(m.file_size for m in members) > MAX_EXPANDED_BYTES:
            fail('Excel 解压后超过 5 MB，请拆分导出', 413)
        if any(m.flag_bits & 1 or m.file_size > MAX_EXPANDED_BYTES or
               m.file_size > max(100_000, m.compress_size * 200) or
               m.filename.startswith('/') or '..' in m.filename.split('/') for m in members):
            fail('Excel 压缩包结构不受支持，请重新导出纯数据文件')
        names = set(archive.namelist())
        if any('vbaproject' in name.lower() or 'externallinks/' in name.lower() for name in names):
            fail('请选择不含宏或外部链接的 XLSX 数据文件')

        def read_xml(name):
            if name not in names:
                fail('Excel 缺少工作簿或数据表，请重新导出')
            try:
                return safe_xml(archive.read(name))
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
                fail('Excel 压缩数据损坏或加密，请重新导出')

        workbook = read_xml('xl/workbook.xml')
        sheets = workbook.findall('s:sheets/s:sheet', XLSX_NS)
        visible = [s for s in sheets if s.get('state', 'visible') == 'visible']
        if not visible:
            fail('Excel 中没有可见的数据表')
        relation_id = visible[0].get('{' + REL_NS + '}id')
        relations = read_xml('xl/_rels/workbook.xml.rels')
        relation = next((r for r in relations if r.get('Id') == relation_id), None)
        if relation is None or relation.get('TargetMode') == 'External':
            fail('Excel 数据表关系无效')
        target = relation.get('Target', '')
        sheet_path = target.lstrip('/') if target.startswith('/xl/') else posixpath.normpath('xl/' + target)
        if not re.fullmatch(r'xl/worksheets/[^/]+\.xml', sheet_path):
            fail('Excel 数据表路径无效')
        shared = []
        if 'xl/sharedStrings.xml' in names:
            strings = read_xml('xl/sharedStrings.xml')
            for item in strings.findall('s:si', XLSX_NS):
                shared.append(''.join(t.text or '' for t in item.findall('.//s:t', XLSX_NS)))
                if len(shared) > 50_000:
                    fail('Excel 文本数量过多，请拆分文件')
        sheet = read_xml(sheet_path)
        rows = []
        for row in sheet.findall('s:sheetData/s:row', XLSX_NS):
            cells = {}
            for cell in row.findall('s:c', XLSX_NS):
                ref = cell.get('r', '')
                match = re.fullmatch(r'([A-Z]{1,3})([1-9]\d{0,6})', ref)
                if not match:
                    fail('Excel 单元格坐标无效')
                column = 0
                for letter in match[1]:
                    column = column * 26 + ord(letter) - ord('A') + 1
                if column > MAX_COLUMNS or column in cells:
                    fail('Excel 每表最多 100 列，且单元格不能重复')
                if cell.find('s:f', XLSX_NS) is not None:
                    fail('Excel 含有公式；请粘贴为值后导出，系统只接收原始回答')
                kind = cell.get('t', 'n')
                value = cell.findtext('s:v', default='', namespaces=XLSX_NS)
                if kind == 's':
                    try:
                        index = int(value)
                        if index < 0:
                            raise ValueError
                        value = shared[index]
                    except (ValueError, IndexError):
                        fail('Excel 文本索引无效')
                elif kind == 'inlineStr':
                    value = ''.join(t.text or '' for t in cell.findall('.//s:t', XLSX_NS))
                elif kind == 'b':
                    value = 'true' if value == '1' else 'false'
                elif kind not in {'n', 'str'}:
                    fail('Excel 含错误值或不支持的单元格类型，请修正后导出')
                if len(value) > 10_000:
                    fail('单元格内容过长，请保留本次问卷所需字段')
                cells[column] = value
            if cells and any(cells.values()):
                rows.append([cells.get(i, '') for i in range(1, max(cells) + 1)])
            if len(rows) > MAX_ROWS + 1:
                fail('每批最多 1000 条问卷，请分批导入')
        if rows:
            width = len(rows[0])
            rows = [r + [''] * max(0, width - len(r)) for r in rows]
        return rows, len(sheets)


def parse_file(payload):
    extension = payload.filename.rsplit('.', 1)[-1].lower()
    if extension not in {'csv', 'xlsx'}:
        fail('支持 CSV 和 XLSX；旧版 XLS 请先另存为 XLSX 或 CSV')
    try:
        raw = base64.b64decode(payload.content_base64, validate=True)
    except (ValueError, binascii.Error):
        fail('文件编码损坏，请重新选择文件')
    if not raw or len(raw) > MAX_FILE_BYTES:
        fail('请选择小于 1 MB 的文件', 413)
    sheet_count, encoding = 1, 'XLSX'
    if extension == 'xlsx':
        rows, sheet_count = xlsx_rows(raw)
    else:
        if len(raw) > MAX_CSV_BYTES:
            fail('CSV 每批不得超过 500 KB', 413)
        content = None
        for encoding in ('utf-8-sig', 'gb18030'):
            try:
                content = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                pass
        if content is None or '\x00' in content:
            fail('CSV 编码不受支持，请导出为 UTF-8 或 GB18030')
        try:
            rows = []
            for row in csv.reader(io.StringIO(content, newline=''), strict=True):
                if not row or not any(cell.strip() for cell in row):
                    continue
                if len(row) > MAX_COLUMNS or any(len(cell) > 10_000 for cell in row):
                    fail('CSV 每行最多 100 列，单元格内容不超过 10000 字符')
                rows.append(row)
                if len(rows) > MAX_ROWS + 1:
                    fail('每批最多 1000 条问卷，请分批导入')
        except csv.Error:
            fail('CSV 引号或分隔符损坏，请使用带表头的逗号分隔文件')
    if len(rows) < 2:
        fail('文件须包含一行表头和至少一条问卷记录')
    headers = [header.strip().lstrip('\ufeff') for header in rows[0]]
    if any(not h or len(h) > 300 for h in headers) or len(set(headers)) != len(headers):
        fail('表头不能留空、重复或超过 300 字符，请修正后重试')
    writer_buffer = io.StringIO(newline='')
    csv.writer(writer_buffer).writerows([headers, *rows[1:]])
    if len(writer_buffer.getvalue().encode('utf-8')) > MAX_CSV_BYTES:
        fail('转换后的 CSV 超过 500 KB，请拆分导入', 413)
    return ParsedExport(headers, rows[1:], extension, encoding, hashlib.sha256(raw).hexdigest(), sheet_count)


def suggested_mapping(headers):
    result = {}
    for key in CSV_REQUIRED + CSV_OPTIONAL:
        matches = [h for h in [key, *EXPORT_ALIASES.get(key, [])] if h in headers and not sensitive_header(h)]
        if len(matches) == 1:
            result[key] = matches[0]
    return result


def answer_value(value):
    if value in SCALE_LABELS:
        return SCALE_LABELS[value]
    # Common survey exports prepend the option number. Require the number and
    # the exact instrument label to agree; never infer arbitrary Likert scales.
    match = re.fullmatch(r'([1-5])\s*[.、．:：)）-]\s*(.+)', value)
    if match and SCALE_LABELS.get(match[2]) == match[1]:
        return match[1]
    return value


@router.post('/file/inspect')
def inspect_file(payload: FileInput, user=Depends(administrator)):
    parsed = parse_file(payload)
    headers = [h for h in parsed.headers if not sensitive_header(h)]
    # Values of arbitrary, as-yet-unmapped fields must not be echoed: platform
    # exports often include contact details under custom question titles.
    return {'columns': headers, 'suggested_mapping': suggested_mapping(headers),
            'record_count': len(parsed.rows), 'format': parsed.format, 'encoding': parsed.encoding,
            'sheet_count': parsed.sheet_count, 'removed_personal_columns': len(parsed.headers) - len(headers),
            'preview_rows': [{'line': i, 'column_count': len(row), 'shape_valid': len(row) == len(parsed.headers)}
                             for i, row in enumerate(parsed.rows[:5], 2)],
            'instrument_version': INSTRUMENT_VERSION,
            'notice': '仅读取第一张可见数据表；此步骤不保存文件或问卷。预览不展示原始个人信息。'}


def prepare_import(payload):
    if payload.instrument_version != INSTRUMENT_VERSION or not payload.instrument_confirmed:
        fail('请先核对导出题目与本平台 30 题职业活动兴趣问卷完全对应；其他问卷不能转换为此兴趣得分')
    if payload.data_kind == 'authorized' and not payload.authorized_consent:
        fail('真实问卷需确认已取得使用授权；每条记录仍须有本人同意列')
    parsed = parse_file(payload)
    if any(sensitive_header(h) for h in payload.field_mapping.values()):
        fail('不能映射个人身份或联系方式列，请使用答卷编号')
    # All 30 columns must be identified; individual answers may remain blank.
    csv_payload = SurveyCSVImport(source_name=payload.source_name, data_kind=payload.data_kind,
        authorized_consent=payload.authorized_consent, csv_content='placeholder',
        field_mapping=payload.field_mapping,
        ignore_columns=list(set(payload.ignore_columns) | {h for h in parsed.headers if sensitive_header(h)}))
    mapping, ignored, _ = export_column_mapping(parsed.headers, csv_payload)
    missing = set(QUESTION_IDS) - set(mapping)
    if missing:
        fail('请对应全部 30 道题的列（单条答案可为空）；尚未对应：' + '、'.join(sorted(missing)))
    if 'response_id' not in mapping or 'consent' not in mapping:
        fail('必须对应答卷编号和本人同意授权列')
    indices = {key: parsed.headers.index(header) for key, header in mapping.items()}
    records = []
    for row in parsed.rows:
        if len(row) != len(parsed.headers):
            records.append({'invalid_columns': True})
            continue
        # Spreadsheet-looking formula text is never evaluated, retained or
        # passed through to downstream CSV export in a whitelisted field.
        values = {key: row[index].strip() for key, index in indices.items()}
        if any(value.lstrip().startswith(('=', '+', '@')) for value in values.values()):
            records.append({'invalid_formula': True})
            continue
        record = {key: value for key, value in values.items() if key not in QUESTION_IDS and key != 'consent'}
        record['answers'] = {key: answer_value(values[key]) for key in QUESTION_IDS}
        record['consent'] = values['consent'].lower() in {'true', '是', '同意', '已授权'}
        raw_id = record.get('response_id', '')
        identity = record.get('student_key') or raw_id
        scope = payload.source_name.strip() + '\0'
        record['response_id'] = 'export_' + hashlib.sha256((scope + raw_id).encode()).hexdigest()[:40] if raw_id else ''
        record['student_key'] = 'anon_' + hashlib.sha256((scope + identity).encode()).hexdigest()[:40] if identity else ''
        records.append(record)
    try:
        imported = SurveyImport(source_name=payload.source_name, data_kind=payload.data_kind,
            authorized_consent=payload.authorized_consent, records=records)
    except ValueError:
        fail('来源名称无效，self: 为本人问卷保留来源')
    raw_records = canonical_json(records)
    if len(raw_records.encode('utf-8')) > MAX_CSV_BYTES:
        fail('规范化后的数据超过 500 KB，请拆分导入', 413)
    metadata = {'format': parsed.format, 'encoding': parsed.encoding, 'sheet_count': parsed.sheet_count,
                'mapped_fields': sorted(mapping), 'ignored_column_count': len(ignored),
                'removed_personal_columns': sum(sensitive_header(h) for h in parsed.headers),
                'source_scoped_pseudonyms': True, 'raw_policy': 'validated_consenting_records_only'}
    fingerprint = record_hash({'source_file_hash': parsed.source_hash, 'source_name': imported.source_name,
        'data_kind': payload.data_kind, 'mapping': mapping, 'ignored': sorted(ignored),
        'instrument_version': payload.instrument_version, 'authorized_consent': payload.authorized_consent})
    return imported, parsed, metadata, fingerprint


def preflight(db, payload, parsed, metadata):
    quality = {'total': len(payload.records), 'accepted': 0, 'rejected': 0, 'duplicates': 0,
               'answered_items': 0, 'answer_completeness': None, 'errors': [], 'role_statuses': {}}
    rows, seen = [], {}
    for line, row in enumerate(payload.records, 2):
        try:
            normalized = normalize_external_record(row)
            key, digest = normalized['response_id'], record_hash(normalized)
            previous = seen.get(key)
            if previous is None:
                existing = db.scalar(select(InterestResponse).where(InterestResponse.source_name == payload.source_name,
                    InterestResponse.data_kind == payload.data_kind, InterestResponse.response_key == key))
                previous = existing.answer_hash if existing else None
            if previous is not None:
                if previous != digest:
                    raise ValueError('同一来源与问卷编号存在不同答案；本行拒绝，原记录不覆盖')
                quality['duplicates'] += 1
                rows.append({'line': line, 'status': 'duplicate', 'reason': '相同答卷已存在，将跳过'})
                continue
            seen[key] = digest
            result = score_answers(normalized['answers'])
            quality['accepted'] += 1
            quality['answered_items'] += result['coverage']['answered_items']
            quality['role_statuses'][result['status']] = quality['role_statuses'].get(result['status'], 0) + 1
            rows.append({'line': line, 'status': 'accepted', 'answered_items': result['coverage']['answered_items'],
                         'role_status': result['status'], 'reason': '可导入；原始值已完成规范校验'})
        except ValueError as exc:
            quality['rejected'] += 1
            reason = '记录列数或公式文本不符合导入要求' if 'invalid_columns' in row or 'invalid_formula' in row else str(exc)
            quality['errors'].append({'line': line, 'reason': reason})
            rows.append({'line': line, 'status': 'rejected', 'reason': reason})
    if quality['accepted']:
        quality['answer_completeness'] = round(quality['answered_items'] / (quality['accepted'] * 30), 4)
    return {'quality': quality, 'rows': rows[:100], 'rows_truncated': len(rows) > 100,
            'export_metadata': metadata, 'source_file_hash': parsed.source_hash,
            'notice': '预检未保存数据。确认后重新校验并入库；并发导入可能使重复数量发生变化。'}


@router.post('/preview')
def preview_import(payload: ImportInput, user=Depends(administrator), db=Depends(get_db)):
    imported, parsed, metadata, fingerprint = prepare_import(payload)
    return preflight(db, imported, parsed, metadata) | {'preview_fingerprint': fingerprint}


@router.post('/commit')
def commit_import(payload: CommitInput, user=Depends(administrator), db=Depends(get_db)):
    imported, parsed, metadata, fingerprint = prepare_import(payload)
    if payload.preview_fingerprint != fingerprint:
        fail('文件、来源或字段对应已改变，请重新预检后确认导入', 409)
    return import_surveys(db, user.id, imported, raw_content=canonical_json(imported.records), line_offset=2,
                          source_file_hash=parsed.source_hash, export_metadata=metadata)
