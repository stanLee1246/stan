"""Crawler boundary, provenance and idempotence tests; all HTTP is mocked."""
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.crawl_models import CrawlRun, RawCrawlDocument
from app.crawling import (MAX_BODY_BYTES, CrawlerHTTP, CrawlError, CrawlInput, SOURCES,
                          parse_detail, parse_list, run_crawl, safe_url, seed_crawl_demo)
from app.database import SessionLocal
from app.models import Opportunity, User

SOURCE = SOURCES['hengyang_hr_public']
FIXTURES = Path(__file__).resolve().parents[2] / 'data' / 'crawler-fixtures'
LIST = (FIXTURES / 'official-list-sample.html').read_text(encoding='utf-8')
DETAIL = (FIXTURES / 'official-detail-sample.html').read_text(encoding='utf-8')


def fetcher(handler):
    return CrawlerHTTP(SOURCE, client=httpx.Client(transport=httpx.MockTransport(handler)),
                       resolver=lambda host: None, sleeper=lambda delay: None)


def good_fetcher(*, detail=DETAIL, robots='User-agent: *\nAllow: /'):
    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=robots, headers={'content-type': 'text/plain'})
        return httpx.Response(200, text=LIST if request.url.path.endswith('/index.html') else detail,
                              headers={'content-type': 'text/html; charset=utf-8'})
    return fetcher(handler)


def actor(db):
    return db.scalar(select(User).where(User.username == 'admin_user')).id


def test_list_detail_parsing_uses_explicit_date_and_preserves_unknown_requirements():
    entries = parse_list(LIST, SOURCE, 9)
    assert len(entries) == 2
    assert all(item['url'].startswith('https://www.hengyang.gov.cn/') for item in entries)
    parsed = parse_detail(DETAIL)
    assert parsed['published_at'].isoformat() == '2026-10-01'
    assert parsed['title'] == '衡阳市事业单位公开招聘工作人员公告'
    assert 'notContent' not in parsed['description']
    assert '网站导航' not in parsed['description']
    assert parse_detail('<h1>测试招聘公告</h1><p>报名从2026-10-09开始。</p>')['published_at'] is None
    assert parse_detail('<h1>测试招聘公告</h1><p>报名时间：2026-10-09</p>')['published_at'] is None
    assert parse_detail('<h1>招聘公告</h1><div>发布时间：2026年10月2日</div><div class="TRS_Editor">条件请看附件</div>')['published_at'].isoformat() == '2026-10-02'


@pytest.mark.parametrize('url', ['http://www.hengyang.gov.cn/x.html', 'https://127.0.0.1/x.html',
    'https://www.hengyang.gov.cn@evil.example/x.html', 'https://www.hengyang.gov.cn/x.html?target=localhost',
    'https://www.hengyang.gov.cn:8443/x.html', 'https://www.hengyang.gov.cn/x.html\nHeader: bad'])
def test_only_fixed_https_host_without_query_or_credentials(url):
    with pytest.raises(CrawlError):
        safe_url(url, SOURCE)


def test_cross_host_redirect_and_oversized_body_are_blocked():
    redirect = fetcher(lambda request: httpx.Response(302, headers={'location': 'https://localhost/private'}))
    with pytest.raises(CrawlError, match='未注册主机'):
        redirect.request(SOURCE.url)
    large = fetcher(lambda request: httpx.Response(200, headers={'content-length': str(MAX_BODY_BYTES + 1)}))
    with pytest.raises(CrawlError, match='大小限制'):
        large.request(SOURCE.url)


def test_private_dns_resolution_blocks_before_request(monkeypatch):
    from app.crawling import public_dns
    monkeypatch.setattr('app.crawling.socket.getaddrinfo', lambda *args, **kwargs: [(2, 1, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(CrawlError, match='非公共网络'):
        public_dns('www.hengyang.gov.cn')


def test_registered_host_dns_can_use_already_configured_https_proxy(monkeypatch):
    from app.crawling import public_dns
    def unavailable(*args, **kwargs):
        raise OSError('mock DNS unavailable')
    monkeypatch.setattr('app.crawling.socket.getaddrinfo', unavailable)
    for name in ('HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(CrawlError, match='无法解析'):
        public_dns(SOURCE.allowed_host)
    monkeypatch.setenv('HTTPS_PROXY', 'http://proxy.example:8080')
    assert public_dns(SOURCE.allowed_host) is None


def test_robots_disallow_is_persisted_without_fetching_list(client):
    with SessionLocal() as db:
        result = run_crawl(db, actor(db), CrawlInput(source_id=SOURCE.id),
                           good_fetcher(robots='User-agent: *\nDisallow: /hysrsj/'))
        assert result['status'] == 'blocked'
        assert result['accepted'] == 0
        assert result['errors'][0]['code'] == 'robots_disallowed'
        assert not result['documents']


def test_crawl_ingests_notice_raw_provenance_deduplicates_and_versions(client):
    with SessionLocal() as db:
        request = CrawlInput(source_id=SOURCE.id, limit=1)
        first = run_crawl(db, actor(db), request, good_fetcher())
        assert first['status'] == 'completed' and first['accepted'] == 1
        raw = db.scalar(select(RawCrawlDocument).where(RawCrawlDocument.run_id == first['run_id'],
                         RawCrawlDocument.opportunity_id.is_not(None)))
        assert raw.raw_content == DETAIL
        assert raw.parsed_metadata['requirements_review'] is True
        opportunity = db.get(Opportunity, raw.opportunity_id)
        assert opportunity.data_kind == 'public'
        assert opportunity.minimum_degree is None and opportunity.deadline is None
        assert opportunity.skills == [] and opportunity.majors == []
        assert opportunity.requirements_verified is False
        second = run_crawl(db, actor(db), request, good_fetcher())
        assert second['accepted'] == 0 and second['duplicates'] == 1
        changed = DETAIL.replace('具体报名时间另行通知', '公告内容发生真实更新，具体报名时间另行通知')
        third = run_crawl(db, actor(db), request, good_fetcher(detail=changed))
        assert third['accepted'] == 1
        versions = list(db.scalars(select(Opportunity).order_by(Opportunity.version)))
        assert [record.version for record in versions] == [1, 2]


def test_failed_real_crawl_fallback_is_explicit_demo_and_keeps_real_error(client):
    blocked = fetcher(lambda request: httpx.Response(403))
    with SessionLocal() as db:
        result = run_crawl(db, actor(db), CrawlInput(source_id=SOURCE.id, limit=8, allow_demo_fallback=True), blocked)
        assert result['status'] == 'demo_fallback'
        assert result['data_kind'] == 'demo' and result['accepted'] == 8
        assert result['errors'][0]['code'] == 'http_status'
        items = list(db.scalars(select(Opportunity)))
        assert len(items) == 8
        assert all(item.data_kind == 'demo' and item.title.startswith('（模拟）') for item in items)
        assert all(item.source_url.startswith('https://example.com/') for item in items)
        assert all(item.published_at is None and item.deadline is None for item in items)
        documents = list(db.scalars(select(RawCrawlDocument)))
        assert all(doc.parsed_metadata['origin'] == 'synthetic' for doc in documents)


def test_large_chinese_notice_keeps_complete_raw_and_clips_mysql_text_excerpt(client):
    long_body = '招聘条件请核对完整公告附件。' * 2000  # >25,000 Chinese characters / >65,535 UTF-8 bytes.
    html = f'<h1>衡阳事业单位招聘长公告</h1><div class="TRS_Editor">{long_body}</div>'
    assert len(long_body) > 25000 and len(long_body.encode('utf-8')) > 65535
    with SessionLocal() as db:
        request = CrawlInput(source_id=SOURCE.id, limit=1)
        result = run_crawl(db, actor(db), request, good_fetcher(detail=html))
        assert result['status'] == 'completed' and result['accepted'] == 1
        document = db.scalar(select(RawCrawlDocument).where(RawCrawlDocument.run_id == result['run_id'],
                             RawCrawlDocument.opportunity_id.is_not(None)))
        opportunity = db.get(Opportunity, document.opportunity_id)
        assert document.raw_content == html
        assert opportunity.description == long_body[:10000]
        assert len(opportunity.description) == 10000
        assert len(opportunity.description.encode('utf-8')) <= 40000
        assert document.parsed_metadata['description_truncated'] is True
        assert document.parsed_metadata['original_description_length'] == len(long_body)
        # Changes beyond the display excerpt still create a new fact version.
        changed = html.replace('</div>', '正文末尾更新。</div>')
        second = run_crawl(db, actor(db), request, good_fetcher(detail=changed))
        assert second['accepted'] == 1
        assert [o.version for o in db.scalars(select(Opportunity).order_by(Opportunity.version))] == [1, 2]


def test_seed_demo_offline_is_idempotent(client):
    with SessionLocal() as db:
        first = seed_crawl_demo(db, actor(db))
        second = seed_crawl_demo(db, actor(db))
        assert first['accepted'] == 8
        assert second['accepted'] == 0 and second['duplicates'] == 8
        assert len(list(db.scalars(select(Opportunity)))) == 8


def test_crawler_endpoints_require_admin_and_reject_arbitrary_sources(client, student, admin):
    assert client.get('/api/admin/crawler/sources').status_code == 401
    assert client.get('/api/admin/crawler/sources', headers=student).status_code == 403
    sources = client.get('/api/admin/crawler/sources', headers=admin)
    assert sources.status_code == 200 and isinstance(sources.json(), list)
    result = client.post('/api/admin/crawler/run', headers=admin, json={'source_id': 'evil', 'limit': 1})
    assert result.status_code == 400
    assert client.post('/api/admin/crawler/run', headers=admin, json={'source_id': SOURCE.id, 'limit': 11}).status_code == 422
    assert client.get('/api/admin/crawler/runs', headers=student).status_code == 403
