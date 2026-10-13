"""Local database preparation: python -m app.cli init-db [--demo]."""
import argparse
import csv
import io
import os
import re
from datetime import date, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text

from .database import ROOT, SessionLocal, database_url, engine
from .models import Opportunity, User
from .schemas import ImportInput
from .security import hash_password
from .services import REQUIRED_COLUMNS, import_outcomes

DEMO_SOURCE = '演示样本：非真实校友记录'


def migrate():
    if engine.dialect.name == 'mysql':
        name = os.getenv('DB_NAME', 'career_platform')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name):
            raise ValueError('DB_NAME 只能包含英文字母、数字和下划线，且以字母开头')
        server = create_engine(database_url(include_database=False), pool_pre_ping=True)
        with server.begin() as connection:
            connection.execute(text(f'CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
        server.dispose()
    cfg = Config(str(ROOT / 'alembic.ini'))
    cfg.set_main_option('script_location', str(ROOT / 'migrations'))
    command.upgrade(cfg, 'head')


def demo_csv():
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(REQUIRED_COLUMNS)
    # Deterministic synthetic records; historical dates are not real school statistics.
    for i in range(180):
        writer.writerow([f'demo_{i:06d}', '数据科学与大数据技术' if i < 120 else '软件工程',
                         2023 + i % 3, ['employment', 'postgraduate', 'civil_service', 'public_institution', 'unresolved', 'other'][i % 6],
                         ['衡阳', '长沙市', '广州', '深圳市'][i % 4], '2026-09-01',
                         'simulated', f'demo-row-{i}', 'https://example.com/synthetic-outcomes'])
    return stream.getvalue()


def seed_demo():
    with SessionLocal() as db:
        for username, nickname, role, password in [
            ('demo_student', '演示学生', 'student', 'DemoStudent123!'),
            ('demo_admin', '演示管理员', 'admin', 'DemoAdmin123!'),
        ]:
            if not db.scalar(select(User).where(User.username == username)):
                db.add(User(username=username, nickname=nickname, role=role, password_hash=hash_password(password)))
        db.commit()
        admin = db.scalar(select(User).where(User.username == 'demo_admin'))
        result = import_outcomes(db, admin.id, ImportInput(source_name=DEMO_SOURCE, csv_content=demo_csv()))
        items = [
            ('employment', '数据分析实习转正岗（模拟）', '衡阳', ['Python', 'SQL', 'Excel']),
            ('employment', '数据仓库开发岗（模拟）', '长沙', ['SQL', 'MySQL', 'Python']),
            ('employment', '前端开发岗（模拟）', '深圳', ['Vue', 'ECharts', 'Java']),
            ('internship', '商业分析实习（模拟）', '广州', ['Excel', 'SQL']),
            ('postgraduate', '计算机技术研究生项目（模拟）', '长沙', []),
            ('civil_service', '统计类公务员职位（模拟）', '衡阳', []),
            ('public_institution', '信息技术事业单位岗位（模拟）', '长沙', ['Python']),
        ]
        for i, (path, title, city, skills) in enumerate(items):
            key = f'demo-opportunity-{i}'
            if db.scalar(select(Opportunity).where(Opportunity.source_record_id == key)):
                continue
            db.add(Opportunity(source_record_id=key, title=title, organization='虚构演示单位', path=path,
                               city=city, skills=skills, majors=['数据科学与大数据技术', '软件工程'],
                               minimum_degree='bachelor', description='仅用于验证筛选、画像和推荐链路，不是真实招生或招聘信息。正式资格条件请核对真实公告。',
                               deadline=date.today() + timedelta(days=90), published_at=date.today(),
                               source_url=f'https://example.com/demo/{i}', data_kind='demo', requirements_verified=False))
        db.commit()
        print(f"演示数据准备完成：新增 {result['quality']['accepted']}，重复 {result['quality']['duplicates']}。")
        from .demo_data import seed_extended_opportunities
        from .interests import seed_demo_surveys
        from .crawling import seed_crawl_demo
        extra = seed_extended_opportunities(db)
        seed_demo_surveys(db, admin.id)
        seed_crawl_demo(db, admin.id)
        print(f'已准备职业探索与多维图表案例：新增扩展机会 {extra} 条；问卷和采集演示均独立标记为模拟。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['init-db', 'seed-demo', 'create-admin', 'export-demo'])
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--output', default=str(ROOT.parent / 'data' / 'demo-outcomes.csv'))
    args = parser.parse_args()
    if args.action == 'init-db':
        migrate()
        print(f'数据库迁移完成（{engine.dialect.name}）。')
        if args.demo:
            seed_demo()
    elif args.action == 'seed-demo':
        seed_demo()
    elif args.action == 'export-demo':
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(demo_csv(), encoding='utf-8-sig')
        print('模拟 CSV 已导出。')
    elif args.action == 'create-admin':
        import getpass
        from .schemas import Register
        payload = Register(username=input('管理员用户名: '), nickname=input('公开昵称: '), password=getpass.getpass('管理员密码（至少10位）: '))
        with SessionLocal() as db:
            if db.scalar(select(User).where(User.username == payload.username)):
                raise SystemExit('用户名已存在；未修改该账户。')
            db.add(User(username=payload.username, nickname=payload.nickname, password_hash=hash_password(payload.password), role='admin'))
            db.commit()
        print('管理员已创建。')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not echo database URLs or parameters containing credentials.
        code = getattr(exc, 'orig', exc).args
        identifier = str(code[0]) if code and isinstance(code[0], int) else type(exc).__name__
        raise SystemExit(f'初始化失败（{identifier}）。请检查 MySQL 服务、backend/.env、数据库创建权限及迁移配置；凭据不会写入日志。')
