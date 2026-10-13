"""Small, auditable official-notice crawler; no user-supplied URL fetching."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import time
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .auth import administrator
from .crawl_models import CrawlRun, RawCrawlDocument
from .database import get_db
from .models import AuditEvent, Opportunity, now

USER_AGENT = 'CareerResearchCrawler/1.0 (+local academic research; bounded public notices)'
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_CONTENT_PAGES = 10  # One list plus at most nine details. Robots is a policy request.
PARSER_VERSION = 'hengyang-notice-v1'


@dataclass(frozen=True)
class CrawlSource:
    id: str
    name: str
    url: str
    path: str
    allowed_host: str
    organization: str


SOURCES = {
    'hengyang_hr_public': CrawlSource(
        'hengyang_hr_public', '衡阳市人社局事业单位公开招聘公告',
        'https://www.hengyang.gov.cn/hysrsj/ywgz/sydwgkzp/index.html',
        'public_institution', 'www.hengyang.gov.cn', '衡阳市人力资源和社会保障局（公告发布方）',
    ),
}
router = APIRouter(prefix='/api/admin/crawler', tags=['公告采集'])


class CrawlInput(BaseModel):
    source_id: str = Field(min_length=1, max_length=60, pattern=r'^[a-z0-9_]+$')
    limit: int = Field(default=5, ge=1, le=10)
    allow_demo_fallback: bool = False


class CrawlError(Exception):
    def __init__(self, code: str, message: str, url: str | None = None):
        self.code, self.message, self.url = code, message, url
        super().__init__(message)

    def as_dict(self):
        value = {'code': self.code, 'message': self.message}
        if self.url:
            value['url'] = self.url
        return value


def safe_url(url: str, source: CrawlSource) -> str:
    """Every original/redirect/detail URL stays on the fixed HTTPS source host."""
    try:
        parts = urlsplit(url)
        invalid_port = parts.port not in (None, 443)
    except ValueError:
        raise CrawlError('unsafe_url', '拒绝无效的公告地址') from None
    if (parts.scheme != 'https' or parts.hostname != source.allowed_host or parts.username
            or parts.password or invalid_port or parts.query or len(url) > 255
            or any(character in url for character in ('\\', '\r', '\n', '\x00'))):
        raise CrawlError('unsafe_url', '拒绝未注册主机、非 HTTPS、凭据、查询参数或过长地址')
    # The source hostname must be a domain; IP literals (including localhost) are never allowed.
    try:
        ipaddress.ip_address(parts.hostname)
    except ValueError:
        pass
    else:
        raise CrawlError('unsafe_url', '拒绝 IP 地址来源')
    return urlunsplit((parts.scheme, parts.netloc, parts.path or '/', '', ''))


def public_dns(host: str):
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        # The platform's HTTPS proxy can resolve the fixed official host remotely.
        # Only an already configured proxy may supply DNS; arbitrary source hosts
        # are still rejected by safe_url before this function is reached.
        if any(os.getenv(name) for name in ('HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy')):
            return
        raise CrawlError('dns_failed', '无法解析已注册官方来源域名') from None
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise CrawlError('private_address', '拒绝解析到非公共网络地址的来源')


class CrawlerHTTP:
    """TLS on, fixed host, bounded streaming, no automatic redirects, one-second spacing."""
    def __init__(self, source: CrawlSource, client: httpx.Client | None = None,
                 resolver=public_dns, sleeper=time.sleep):
        self.source = source
        self.client = client or httpx.Client(timeout=httpx.Timeout(15, connect=10), verify=True,
                                           follow_redirects=False, headers={'User-Agent': USER_AGENT})
        self.owns_client = client is None
        self.resolver, self.sleeper = resolver, sleeper
        self.last_request = 0.0
        self.robots: RobotFileParser | None = None

    def close(self):
        if self.owns_client:
            self.client.close()

    def request(self, url: str, *, robots=False) -> tuple[str, str, int]:
        original = safe_url(url, self.source)
        current = original
        for _ in range(4):
            current = safe_url(current, self.source)
            self.resolver(self.source.allowed_host)
            if not robots and self.robots is not None and not self.robots.can_fetch(USER_AGENT, current):
                raise CrawlError('robots_disallowed', 'robots.txt 禁止采集此页面', current)
            delay = 1.0 - (time.monotonic() - self.last_request)
            if delay > 0:
                self.sleeper(delay)
            self.last_request = time.monotonic()
            try:
                with self.client.stream('GET', current, headers={'User-Agent': USER_AGENT}) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get('location')
                        if not location:
                            raise CrawlError('redirect_failed', '官方页面重定向未给出目标地址', current)
                        current = safe_url(urljoin(current, location), self.source)
                        continue
                    if robots and response.status_code in (404, 410):
                        return '', current, response.status_code
                    if response.status_code != 200:
                        raise CrawlError('http_status', f'官方来源返回 HTTP {response.status_code}；未尝试绕过访问限制', current)
                    declared = response.headers.get('content-length', '')
                    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
                        raise CrawlError('body_too_large', '页面超过 2 MiB 大小限制', current)
                    if not robots:
                        content_type = response.headers.get('content-type', '').lower()
                        if content_type and not any(t in content_type for t in ('text/html', 'application/xhtml+xml')):
                            raise CrawlError('unsupported_content', '只采集 HTML 公告；附件需人工核验', current)
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BODY_BYTES:
                            raise CrawlError('body_too_large', '页面超过 2 MiB 大小限制', current)
                    encoding = response.encoding or 'utf-8'
                    # Legacy official sites sometimes declare charset only inside the document.
                    charset = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', bytes(body[:4096]))
                    if charset:
                        encoding = charset.group(1).decode('ascii')
                    try:
                        html = bytes(body).decode(encoding, errors='replace')
                    except LookupError:
                        html = bytes(body).decode('utf-8', errors='replace')
                    return html, current, response.status_code
            except CrawlError:
                raise
            except httpx.ProxyError as error:
                # Keep only a status number from the diagnostic; never log proxy URLs/credentials.
                code = re.search(r'\b([345]\d{2})\b', str(error))
                detail = f'（HTTP {code.group(1)}）' if code else ''
                raise CrawlError('proxy_blocked', f'云环境代理拒绝或无法建立官方来源 HTTPS 连接{detail}；请检查域名网络许可', current) from None
            except httpx.TimeoutException:
                raise CrawlError('timeout', '官方来源请求超时（连接 10 秒 / 请求 15 秒）', current) from None
            except httpx.HTTPError:
                raise CrawlError('network_error', '官方来源连接失败；TLS 验证保持开启，请检查网络及证书信任', current) from None
        raise CrawlError('redirect_limit', '官方来源重定向次数超过限制', original)

    def load_robots(self):
        url = f'https://{self.source.allowed_host}/robots.txt'
        text, final_url, status = self.request(url, robots=True)
        policy = RobotFileParser(final_url)
        policy.parse(text.splitlines() if status == 200 else [])
        self.robots = policy
        delay = policy.crawl_delay(USER_AGENT)
        rate = policy.request_rate(USER_AGENT)
        rate_interval = rate.seconds / rate.requests if rate and rate.requests else 0
        required_interval = max(delay or 0, rate_interval)
        if required_interval > 1:
            # Keep an admin request bounded rather than silently ignoring a slower site policy.
            raise CrawlError('robots_delay', f'robots.txt 要求至少 {required_interval:g} 秒间隔，超出交互采集策略；请使用获准的离线数据', url)
        if not policy.can_fetch(USER_AGENT, self.source.url):
            raise CrawlError('robots_disallowed', 'robots.txt 禁止采集该来源栏目', self.source.url)


def clean_text(value: str) -> str:
    return re.sub(r'\s+', ' ', value).strip()


def explicit_date(value: str) -> date | None:
    found = re.search(r'(?<!\d)(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})(?:日)?(?!\d)', value)
    if not found:
        return None
    try:
        return date(*(int(part) for part in found.groups()))
    except ValueError:
        return None


class NoticeHTML(HTMLParser):
    """Extract visible text without executing source markup or following page scripts."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool, bool]] = []
        self.metadata: dict[str, str] = {}
        self.anchors: list[dict] = []
        self.current_anchor: dict | None = None
        self.visible: list[str] = []
        self.article: list[str] = []
        self.heading: list[str] = []
        self.doc_title: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            key = (attrs.get('name') or attrs.get('property') or '').lower()
            if key and attrs.get('content'):
                self.metadata[key] = attrs['content']
        marker = (attrs.get('id', '') + ' ' + attrs.get('class', '')).lower()
        article = any(key in marker for key in ('trs_editor', 'article-content', 'article_content', 'news-content', 'news_content', 'zw-content', 'con_txt', 'content-detail', 'articlebody'))
        hidden = tag in ('script', 'style', 'nav', 'header', 'footer')
        if tag not in ('meta', 'br', 'hr', 'img', 'input', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param'):
            self.stack.append((tag, hidden, article))
        if tag == 'a':
            self.current_anchor = {'href': attrs.get('href', ''), 'title': attrs.get('title', ''), 'text': []}

    def handle_endtag(self, tag):
        if tag == 'a' and self.current_anchor:
            anchor = self.current_anchor
            anchor['text'] = clean_text(' '.join(anchor['text']))
            self.anchors.append(anchor)
            self.current_anchor = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        text = clean_text(data)
        if not text or any(hidden for _, hidden, _ in self.stack):
            return
        if self.current_anchor:
            self.current_anchor['text'].append(text)
        self.visible.append(text)
        if any(article for _, _, article in self.stack):
            self.article.append(text)
        if any(tag == 'h1' for tag, _, _ in self.stack):
            self.heading.append(text)
        if any(tag == 'title' for tag, _, _ in self.stack):
            self.doc_title.append(text)


def parse_list(html: str, source: CrawlSource, limit: int):
    parser = NoticeHTML()
    parser.feed(html)
    entries, seen = [], set()
    for anchor in parser.anchors:
        title = clean_text(anchor['title'] or anchor['text'])
        if not title or not re.search(r'招聘|招考|招录|岗位|录用|人才|就业|实习', title):
            continue
        try:
            url = safe_url(urljoin(source.url, anchor['href']), source)
        except CrawlError:
            continue
        if (url == source.url or url in seen or not re.search(r'\.(?:s?html?|htm)$', urlsplit(url).path, re.I)
                or re.search(r'/(?:index|default)(?:_\d+)?\.', urlsplit(url).path, re.I)):
            continue
        seen.add(url)
        entries.append({'url': url, 'title': title})
        if len(entries) >= limit:
            break
    return entries


def parse_detail(html: str, *, fallback_title: str = ''):
    parser = NoticeHTML()
    parser.feed(html)
    title = clean_text(parser.metadata.get('articletitle') or parser.metadata.get('og:title')
                       or ' '.join(parser.heading) or fallback_title or ' '.join(parser.doc_title))
    body = clean_text(' '.join(parser.article or parser.visible))
    # Only labelled dates or explicit publisher metadata count as a publication date.
    published = None
    for name in ('pubdate', 'publishtime', 'publishdate', 'published_time', 'article:published_time', 'date'):
        if name in parser.metadata:
            published = explicit_date(parser.metadata[name])
            if published:
                break
    if published is None:
        visible = ' '.join(parser.visible)
        for label in re.finditer(r'(?<![\u4e00-\u9fff])(?:发布时间|发布日期|发文时间|时间)\s*[:：]\s*([^\n]{0,35})', visible):
            published = explicit_date(label.group(1))
            if published:
                break
    return {'title': title, 'description': body, 'published_at': published}


def save_document(db, run, source, *, url: str, html: str, parsed: dict, data_kind='public'):
    content_hash = hashlib.sha256(html.encode('utf-8')).hexdigest()
    original_description = parsed['description']
    # Opportunity.description is MySQL TEXT (65,535 bytes); keep its display
    # excerpt aligned with the 10,000-character OpportunityInput constraint.
    # The complete decoded source remains available in the LONGTEXT raw table.
    description = original_description[:10000]
    description_hash = hashlib.sha256(original_description.encode('utf-8')).hexdigest()
    timestamp = now()
    metadata = {
        'title': parsed['title'], 'published_at': parsed.get('published_at').isoformat() if parsed.get('published_at') else None,
        'deadline': None, 'requirements_review': True, 'record_type': 'announcement',
        'origin': 'synthetic' if data_kind == 'demo' else 'official_public_page',
        'path': parsed.get('path', source.path), 'publisher': source.organization,
        'content_hash_basis': 'decoded_html_utf8', 'parser_version': PARSER_VERSION,
        'description_truncated': len(original_description) > len(description),
        'original_description_length': len(original_description),
        'description_hash': description_hash,
    }
    document = RawCrawlDocument(run_id=run.id, source_id=source.id, source_url=url,
                               title=parsed['title'][:150], raw_content=html, content_hash=content_hash,
                               parsed_metadata=metadata, data_kind=data_kind, fetched_at=timestamp)
    db.add(document)
    if not parsed['title'] or len(description) < 25:
        document.parsed_status = 'rejected'
        metadata['rejection_reason'] = '标题缺失或正文过短，需人工核验页面模板'
        document.parsed_metadata = metadata
        run.rejected += 1
        return document
    key = ('crawl-demo-' if data_kind == 'demo' else 'crawl-public-') + hashlib.sha256(url.encode()).hexdigest()[:40]
    latest = db.scalar(select(Opportunity).where(Opportunity.source_url == url,
                       Opportunity.source_record_id == key).order_by(Opportunity.version.desc()))
    previous = db.scalar(select(RawCrawlDocument).where(RawCrawlDocument.source_url == url,
                         RawCrawlDocument.data_kind == data_kind, RawCrawlDocument.opportunity_id.is_not(None))
                         .order_by(RawCrawlDocument.id.desc()))
    # Both raw equality and extracted fact equality prevent template-only changes from adding fact versions.
    same_facts = latest is not None and (latest.title == parsed['title'][:150]
                 and latest.description == description and latest.published_at == parsed.get('published_at')
                 and latest.path == parsed.get('path', source.path)
                 and previous is not None and previous.parsed_metadata.get('description_hash') == description_hash)
    if latest is not None and (same_facts or previous and previous.content_hash == content_hash):
        document.parsed_status = 'duplicate'
        document.opportunity_id = latest.id
        run.duplicates += 1
        return document
    opportunity = Opportunity(source_record_id=key, version=latest.version + 1 if latest else 1,
        title=parsed['title'][:150], organization=source.organization, path=parsed.get('path', source.path),
        organization_type='public_notice' if data_kind == 'public' else 'synthetic', city='衡阳',
        skills=[], majors=[], minimum_degree=None, description=description, deadline=None,
        published_at=parsed.get('published_at'), source_url=url, data_kind=data_kind,
        requirements_verified=False, fetched_at=timestamp)
    db.add(opportunity)
    db.flush()
    document.opportunity_id = opportunity.id
    document.parsed_status = 'requirements_review'
    run.accepted += 1
    return document


def demo_source():
    return CrawlSource('hengyang_local_demo', '衡阳职业机会合成样本', 'https://example.com/synthetic-hengyang',
                       'employment', 'example.com', '虚构衡阳演示单位（非真实招聘主体）')


def add_demo_documents(db, run, limit=8):
    path = Path(__file__).resolve().parents[2] / 'data' / 'crawler-fixtures' / 'hengyang-demo.json'
    fixtures = json.loads(path.read_text(encoding='utf-8'))
    source = demo_source()
    for fixture in fixtures[:limit]:
        parsed = {**fixture, 'published_at': None}
        html = json.dumps(fixture, ensure_ascii=False, sort_keys=True)
        save_document(db, run, source, url=f"https://example.com/synthetic-hengyang/{fixture['id']}",
                      html=html, parsed=parsed, data_kind='demo')


def finish_run(db, run):
    run.finished_at = now()
    documents = list(db.scalars(select(RawCrawlDocument).where(RawCrawlDocument.run_id == run.id)))
    details = [doc for doc in documents if doc.parsed_status != 'list_page']
    run.quality = {**run.quality, 'accepted': run.accepted, 'duplicates': run.duplicates,
        'rejected': run.rejected, 'documents': len(documents), 'unverified_requirements': sum(
            d.parsed_status == 'requirements_review' for d in documents),
        'missing_publication_date': sum(not d.parsed_metadata.get('published_at') for d in details),
        'unknown_deadlines': len(details), 'data_kind': run.data_kind,
        'parser_version': PARSER_VERSION, 'raw_hash_algorithm': 'sha256',
        'max_content_pages': MAX_CONTENT_PAGES, 'min_interval_seconds': 1,
        'note': '栏目公告不等于独立岗位；具体专业、学历、报名条件及截止日期需核对公告及附件。'}
    db.add(AuditEvent(actor_id=run.imported_by, action='crawler_run', target_id=run.id))
    db.commit()
    return run_dict(db, run)


def seed_crawl_demo(db, admin_id):
    """Idempotent labelled synthetic fixtures for offline/local development, without network."""
    run = CrawlRun(source_id='hengyang_local_demo', imported_by=admin_id, status='demo_fallback',
                   data_kind='demo', requested_limit=8, accepted=0, duplicates=0, rejected=0,
                   errors=[], quality={'fallback_reason': '显式初始化本地模拟数据；未进行真实网络采集'})
    db.add(run)
    db.flush()
    add_demo_documents(db, run)
    return finish_run(db, run)


def run_crawl(db, admin_id, payload: CrawlInput, fetcher: CrawlerHTTP | None = None):
    source = SOURCES.get(payload.source_id)
    if source is None:
        raise HTTPException(400, '未注册的公告来源；不接受任意 URL')
    run = CrawlRun(source_id=source.id, imported_by=admin_id, requested_limit=payload.limit,
                   accepted=0, duplicates=0, rejected=0, errors=[], quality={})
    db.add(run)
    db.flush()
    active = fetcher or CrawlerHTTP(source)
    errors = []
    try:
        active.load_robots()
        listing, list_url, _ = active.request(source.url)
        # Preserve raw listing and its retrieval provenance separately from normalized opportunities.
        db.add(RawCrawlDocument(run_id=run.id, source_id=source.id, source_url=list_url,
            title=source.name, raw_content=listing, content_hash=hashlib.sha256(listing.encode()).hexdigest(),
            parsed_status='list_page', parsed_metadata={'record_type': 'list_page', 'origin': 'official_public_page'},
            data_kind='public', fetched_at=now()))
        entries = parse_list(listing, source, min(payload.limit, MAX_CONTENT_PAGES - 1))
        run.quality = {'candidate_details': len(entries), 'requested_limit': payload.limit,
                       'limit_note': '总计最多 10 个内容页（含 1 个栏目页），最多处理 9 个详情页'}
        if not entries:
            raise CrawlError('no_announcements', '栏目页未发现可解析的招聘公告；模板可能变化，请人工检查', source.url)
        for entry in entries:
            try:
                html, final_url, _ = active.request(entry['url'])
                parsed = parse_detail(html, fallback_title=entry['title'])
                save_document(db, run, source, url=final_url, html=html, parsed=parsed)
            except CrawlError as error:
                run.rejected += 1
                errors.append(error.as_dict())
        run.status = ('partial' if run.accepted or run.duplicates else 'failed') if errors or run.rejected else 'completed'
    except CrawlError as error:
        errors.append(error.as_dict())
        run.status = 'blocked' if error.code in ('proxy_blocked', 'robots_disallowed', 'robots_delay',
                                               'private_address', 'unsafe_url', 'http_status') else 'failed'
    finally:
        if fetcher is None:
            active.close()
    run.errors = errors
    if payload.allow_demo_fallback and run.accepted == 0 and run.duplicates == 0 and (errors or run.rejected):
        run.status, run.data_kind = 'demo_fallback', 'demo'
        run.quality = {**run.quality, 'fallback_reason': '真实来源未得到可用公告；以下仅为合成样本，真实失败保留在 errors'}
        add_demo_documents(db, run, min(payload.limit, 8))
    return finish_run(db, run)


def run_dict(db, run):
    documents = list(db.scalars(select(RawCrawlDocument).where(RawCrawlDocument.run_id == run.id).order_by(RawCrawlDocument.id)))
    return {'run_id': run.id, 'status': run.status, 'source_id': run.source_id,
        'data_kind': run.data_kind, 'accepted': run.accepted, 'duplicates': run.duplicates,
        'rejected': run.rejected, 'errors': run.errors, 'quality': run.quality,
        'started_at': run.started_at, 'finished_at': run.finished_at,
        'documents': [{'id': doc.id, 'title': doc.title, 'source_url': doc.source_url,
            'content_hash': doc.content_hash, 'parsed_status': doc.parsed_status,
            'opportunity_id': doc.opportunity_id, 'data_kind': doc.data_kind,
            'published_at': doc.parsed_metadata.get('published_at'), 'fetched_at': doc.fetched_at}
            for doc in documents]}


@router.get('/sources')
def sources(user=Depends(administrator)):
    return [{'id': value.id, 'name': value.name, 'url': value.url, 'path': value.path,
             'status': 'configured', 'note': '采集前检查 robots.txt；公告条件与附件需人工核验'}
            for value in SOURCES.values()]


@router.post('/run')
def crawl(payload: CrawlInput, user=Depends(administrator), db=Depends(get_db)):
    return run_crawl(db, user.id, payload)


@router.get('/runs')
def runs(user=Depends(administrator), db=Depends(get_db)):
    return [run_dict(db, run) for run in db.scalars(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(30))]
