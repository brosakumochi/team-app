import os
import re
import hmac
import hashlib
import secrets
from datetime import datetime, date, time
from zoneinfo import ZoneInfo

import pandas as pd
import pyotp
import streamlit as st
from sqlalchemy import (
    create_engine, text, MetaData, Table, Column, Integer, String, Boolean,
    DateTime, Date, Text, select, update, delete
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

JST = ZoneInfo("Asia/Tokyo")
APP_TITLE = "BSMGaming チーム管理システム"
DB_URL = os.getenv("DATABASE_URL", "").strip()
OWNER_ID = os.getenv("OWNER_ID", "BSMkuromu").strip()
OWNER_NAME = os.getenv("OWNER_NAME", "オーナー").strip()
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "").strip()
OWNER_TOTP_SECRET = os.getenv("OWNER_TOTP_SECRET", "").strip().replace(" ", "").upper()
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "120"))
MAX_LOGIN_ATTEMPTS = 5

st.set_page_config(page_title=APP_TITLE, page_icon="🗓️", layout="wide")

def now_jst():
    return datetime.now(JST).replace(tzinfo=None)

def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 310_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, expected = stored.split("$", 2)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 310_000).hex()
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def make_engine() -> Engine:
    if DB_URL:
        url = DB_URL
        # Common managed PostgreSQL providers supply postgres:// URLs.
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://") and "+psycopg" not in url:
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return create_engine(url, pool_pre_ping=True, pool_recycle=1800, future=True)
    # Local development only. Hosted deployments should configure DATABASE_URL.
    return create_engine("sqlite:///bsmgaming_team.db", connect_args={"check_same_thread": False}, future=True)

engine = make_engine()
metadata = MetaData()
users_t = Table(
    "users", metadata,
    Column("id", String(80), primary_key=True),
    Column("password_hash", String(300), nullable=False),
    Column("name", String(120), nullable=False),
    Column("role", String(20), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    Column("totp_secret", String(100), nullable=True),
    Column("created_at", DateTime, nullable=False),
)
schedules_t = Table(
    "schedules", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("activity_date", Date, nullable=False),
    Column("user_id", String(80), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime, nullable=False),
)
settings_t = Table(
    "settings", metadata,
    Column("key", String(80), primary_key=True),
    Column("value", Text, nullable=False),
)
metadata.create_all(engine)

DEFAULT_SETTINGS = {
    "theme_bg_color": "#ffffff",
    "theme_text_color": "#202124",
    "theme_icon": "🗓️",
    "maintenance_enabled": "false",
    "maintenance_start": "01:00",
    "maintenance_end": "05:00",
}

def get_setting(conn, key, fallback):
    row = conn.execute(select(settings_t.c.value).where(settings_t.c.key == key)).first()
    return row[0] if row else fallback

def set_setting(conn, key, value):
    exists = conn.execute(select(settings_t.c.key).where(settings_t.c.key == key)).first()
    if exists:
        conn.execute(update(settings_t).where(settings_t.c.key == key).values(value=str(value)))
    else:
        conn.execute(settings_t.insert().values(key=key, value=str(value)))

def seed_database():
    with engine.begin() as conn:
        for key, value in DEFAULT_SETTINGS.items():
            if conn.execute(select(settings_t.c.key).where(settings_t.c.key == key)).first() is None:
                conn.execute(settings_t.insert().values(key=key, value=value))
        # Bootstrap the owner only when the owner ID does not already exist.
        existing = conn.execute(select(users_t.c.id).where(users_t.c.id == OWNER_ID)).first()
        if not existing and OWNER_PASSWORD:
            conn.execute(users_t.insert().values(
                id=OWNER_ID,
                password_hash=password_hash(OWNER_PASSWORD),
                name=OWNER_NAME,
                role="オーナー",
                active=True,
                totp_secret=OWNER_TOTP_SECRET or None,
                created_at=now_jst(),
            ))
        # One-time migration: old default users are not created with known passwords.
        # Admins can create accounts after signing in as owner.

seed_database()

def read_settings():
    with engine.connect() as conn:
        values = dict(DEFAULT_SETTINGS)
        rows = conn.execute(select(settings_t)).mappings().all()
        for row in rows:
            values[row["key"]] = row["value"]
        return values

def list_users(active_only=False):
    with engine.connect() as conn:
        query = select(users_t.c.id, users_t.c.name, users_t.c.role, users_t.c.active, users_t.c.created_at)
        if active_only:
            query = query.where(users_t.c.active.is_(True))
        return [dict(r) for r in conn.execute(query.order_by(users_t.c.created_at)).mappings().all()]

def get_user(user_id):
    with engine.connect() as conn:
        row = conn.execute(select(users_t).where(users_t.c.id == user_id)).mappings().first()
        return dict(row) if row else None

def get_entries(day=None, user_id=None):
    with engine.connect() as conn:
        query = select(schedules_t).order_by(schedules_t.c.activity_date.desc(), schedules_t.c.created_at.desc())
        if day:
            query = query.where(schedules_t.c.activity_date == day)
        if user_id:
            query = query.where(schedules_t.c.user_id == user_id)
        return [dict(r) for r in conn.execute(query).mappings().all()]

def current_maintenance(settings):
    if settings.get("maintenance_enabled", "false").lower() != "true":
        return False
    try:
        start = time.fromisoformat(settings["maintenance_start"])
        end = time.fromisoformat(settings["maintenance_end"])
        current = now_jst().time()
        if start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end
    except Exception:
        return False

def is_owner(user):
    return bool(user and user["role"] == "オーナー")

def is_admin(user):
    return bool(user and user["role"] in ("オーナー", "管理者"))

def logout():
    for key in ("user_id", "authenticated", "login_time", "login_attempts", "totp_pending"):
        st.session_state.pop(key, None)
    st.rerun()

settings = read_settings()
bg = settings.get("theme_bg_color", "#ffffff")
fg = settings.get("theme_text_color", "#202124")
st.markdown(f"""
<style>
.stApp {{ background-color: {bg}; }}
h1, h2, h3, h4, p, label, [data-testid="stMarkdownContainer"] {{ color: {fg}; }}
.small-muted {{ opacity: .8; font-size: .9rem; }}
</style>
""", unsafe_allow_html=True)

if "login_attempts" not in st.session_state:
    st.session_state.login_attempts = 0
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

# Validate active session timeout on every rerun.
if st.session_state.user_id and st.session_state.authenticated:
    login_time = st.session_state.get("login_time")
    if not login_time or (now_jst() - login_time).total_seconds() > SESSION_TIMEOUT_MINUTES * 60:
        logout()

user = get_user(st.session_state.user_id) if st.session_state.user_id else None
if user and (not user["active"]):
    logout()
    user = None

def login_screen():
    st.title("🔑 " + APP_TITLE)
    st.caption("チームメンバー向けログイン")
    if not OWNER_PASSWORD:
        st.warning("初期設定が未完了です。管理者はデプロイ環境の OWNER_PASSWORD を設定してください。")
    with st.form("login_form"):
        uid = st.text_input("ユーザーID", autocomplete="username")
        pw = st.text_input("パスワード", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("ログイン", use_container_width=True)
    if submitted:
        if st.session_state.login_attempts >= MAX_LOGIN_ATTEMPTS:
            st.error("ログイン試行回数の上限に達しました。ページを閉じ、時間をおいて管理者に連絡してください。")
            return
        candidate = get_user(uid.strip())
        if candidate and candidate["active"] and verify_password(pw, candidate["password_hash"]):
            st.session_state.login_attempts = 0
            st.session_state.user_id = candidate["id"]
            st.session_state.login_time = now_jst()
            if candidate["role"] == "オーナー":
                if not candidate.get("totp_secret"):
                    st.session_state.authenticated = True
                    st.session_state.owner_totp_setup_required = True
                else:
                    st.session_state.authenticated = False
                    st.session_state.totp_pending = True
            else:
                st.session_state.authenticated = True
            st.rerun()
        else:
            st.session_state.login_attempts += 1
            remaining = MAX_LOGIN_ATTEMPTS - st.session_state.login_attempts
            if remaining <= 0:
                st.error("ログイン試行回数の上限に達しました。")
            else:
                st.error(f"ユーザーIDまたはパスワードが正しくありません。（残り試行回数: {remaining}回）")

def owner_totp_setup(user_row):
    st.title("🛡️ オーナーの二段階認証を設定")
    st.write("認証アプリ（Google Authenticator、Microsoft Authenticator、1Password など）を用意してください。")
    secret = st.session_state.get("new_totp_secret")
    if not secret:
        secret = pyotp.random_base32()
        st.session_state.new_totp_secret = secret
    uri = pyotp.TOTP(secret).provisioning_uri(name=user_row["id"], issuer_name="BSMGaming")
    st.code(secret)
    st.caption("この秘密鍵は本人だけが見られる安全な場所で保管してください。チャットや公開リポジトリに貼らないでください。")
    st.code(uri, language="text")
    with st.form("setup_totp_form"):
        code = st.text_input("認証アプリに表示された6桁コード", max_chars=6)
        ok = st.form_submit_button("二段階認証を有効にする")
    if ok:
        if code.isdigit() and pyotp.TOTP(secret).verify(code, valid_window=1):
            with engine.begin() as conn:
                conn.execute(update(users_t).where(users_t.c.id == user_row["id"]).values(totp_secret=secret))
            st.session_state.pop("new_totp_secret", None)
            st.session_state.authenticated = True
            st.session_state.pop("owner_totp_setup_required", None)
            st.success("二段階認証を設定しました。")
            st.rerun()
        else:
            st.error("コードを確認できませんでした。認証アプリの最新コードを入力してください。")

def owner_totp_login(user_row):
    st.title("🛡️ オーナー二段階認証")
    st.write(f"アカウント: **{user_row['name']}**")
    with st.form("totp_login_form"):
        code = st.text_input("認証アプリの6桁確認コード", max_chars=6)
        submitted = st.form_submit_button("認証する", use_container_width=True)
    if submitted:
        secret = user_row.get("totp_secret") or ""
        if code.isdigit() and pyotp.TOTP(secret).verify(code, valid_window=1):
            st.session_state.authenticated = True
            st.session_state.login_time = now_jst()
            st.session_state.pop("totp_pending", None)
            st.rerun()
        else:
            st.error("確認コードが正しくありません。認証アプリに表示された最新のコードを確認してください。")
    if st.button("キャンセルしてログイン画面に戻る"):
        logout()

if not user:
    login_screen()
    st.stop()

if st.session_state.get("owner_totp_setup_required"):
    owner_totp_setup(user)
    st.stop()

if user["role"] == "オーナー" and not st.session_state.authenticated:
    owner_totp_login(user)
    st.stop()

if not st.session_state.authenticated:
    st.info("認証状態を確認できません。再度ログインしてください。")
    logout()

# Authenticated main application
settings = read_settings()
maintenance = current_maintenance(settings)
st.sidebar.title(f"{settings.get('theme_icon', '🗓️')} BSMGaming")
st.sidebar.write(f"**{user['name']}**")
st.sidebar.caption(f"権限: {user['role']}")
if st.sidebar.button("ログアウト", use_container_width=True):
    logout()

st.title("🗓️ チームスケジュール・活動履歴管理")
if maintenance and not is_owner(user):
    st.warning(
        f"メンテナンス中です（{settings.get('maintenance_start')}〜{settings.get('maintenance_end')}）。"
        "閲覧はできますが、投稿・変更はできません。"
    )

tab_names = ["カレンダー・活動履歴", "メンバー一覧"]
if is_owner(user):
    tab_names.append("オーナー設定")
elif is_admin(user):
    tab_names.append("管理者機能")
tabs = st.tabs(tab_names)

with tabs[0]:
    st.subheader("活動日を選択")
    chosen_date = st.date_input("対象日", value=date.today(), key="activity_date")
    st.markdown(f"### 📝 {chosen_date.isoformat()} の活動内容・振り返り")
    can_edit = not maintenance or is_owner(user)
    if can_edit:
        with st.form("activity_form", clear_on_submit=True):
            content = st.text_area("活動内容や振り返り", placeholder="大会準備、練習内容、反省点などを入力してください。")
            if is_admin(user):
                members = list_users(active_only=True)
                ids = [m["id"] for m in members]
                default_idx = ids.index(user["id"]) if user["id"] in ids else 0
                assigned_id = st.selectbox("担当メンバー", ids, index=default_idx, format_func=lambda x: next((m["name"] + "（" + m["id"] + "）" for m in members if m["id"] == x), x))
            else:
                assigned_id = user["id"]
                st.caption(f"投稿者: {user['name']}")
            submit = st.form_submit_button("活動履歴を投稿", use_container_width=True)
        if submit:
            cleaned = content.strip()
            if not cleaned:
                st.error("活動内容を入力してください。")
            elif len(cleaned) > 10000:
                st.error("活動内容は10,000文字以内にしてください。")
            else:
                with engine.begin() as conn:
                    conn.execute(schedules_t.insert().values(
                        activity_date=chosen_date,
                        user_id=assigned_id,
                        content=cleaned,
                        created_at=now_jst(),
                    ))
                st.success("活動履歴を保存しました。")
                st.rerun()
    st.divider()
    st.subheader("選択日の活動履歴")
    entries = get_entries(day=chosen_date)
    if not entries:
        st.info("この日の活動履歴はまだありません。")
    for entry in entries:
        member = get_user(entry["user_id"])
        display_name = member["name"] if member else entry["user_id"]
        with st.container(border=True):
            st.markdown(f"**{display_name}**　`{entry['created_at'].strftime('%Y-%m-%d %H:%M')}`")
            st.write(entry["content"])
            if is_admin(user) and (user["role"] == "オーナー" or entry["user_id"] == user["id"]):
                if st.button("この履歴を削除", key=f"delete_entry_{entry['id']}"):
                    with engine.begin() as conn:
                        conn.execute(delete(schedules_t).where(schedules_t.c.id == entry["id"]))
                    st.success("履歴を削除しました。")
                    st.rerun()
    st.divider()
    st.subheader("活動履歴を検索")
    with st.form("search_form"):
        search_start = st.date_input("開始日", value=date.today().replace(day=1))
        search_end = st.date_input("終了日", value=date.today())
        search_text = st.text_input("本文に含まれるキーワード（任意）")
        search_submit = st.form_submit_button("検索")
    if search_submit:
        all_entries = get_entries()
        found = [e for e in all_entries if search_start <= e["activity_date"] <= search_end and search_text.casefold() in e["content"].casefold()]
        if found:
            df = pd.DataFrame([{
                "日付": e["activity_date"].isoformat(),
                "担当ID": e["user_id"],
                "投稿日時": e["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
                "活動内容": e["content"],
            } for e in found])
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button("検索結果をCSVでダウンロード", df.to_csv(index=False).encode("utf-8-sig"), "bsmgaming_activity.csv", "text/csv")
        else:
            st.info("条件に一致する履歴はありません。")

with tabs[1]:
    st.subheader("メンバー一覧")
    members = list_users(active_only=True)
    if members:
        df = pd.DataFrame([{"ユーザーID": m["id"], "表示名": m["name"], "権限": m["role"]} for m in members])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("メンバーが登録されていません。")

if is_owner(user):
    with tabs[2]:
        st.header("👑 オーナー設定")
        st.subheader("メンテナンスモード")
        with st.form("maintenance_form"):
            enabled = st.checkbox("メンテナンスを有効にする", value=settings.get("maintenance_enabled", "false").lower() == "true")
            start_time = st.time_input("開始時刻（日本時間）", value=time.fromisoformat(settings.get("maintenance_start", "01:00")))
            end_time = st.time_input("終了時刻（日本時間）", value=time.fromisoformat(settings.get("maintenance_end", "05:00")))
            save_maintenance = st.form_submit_button("メンテナンス設定を保存")
        if save_maintenance:
            with engine.begin() as conn:
                set_setting(conn, "maintenance_enabled", str(enabled).lower())
                set_setting(conn, "maintenance_start", start_time.strftime("%H:%M"))
                set_setting(conn, "maintenance_end", end_time.strftime("%H:%M"))
            st.success("メンテナンス設定を保存しました。")
            st.rerun()

        st.divider()
        st.subheader("デザイン設定")
        icons = ["🗓️", "🚀", "🛡️", "👥", "🔥", "💻", "⭐", "🏆"]
        with st.form("design_form"):
            icon = st.selectbox("アイコン", icons, index=icons.index(settings.get("theme_icon", "🗓️")) if settings.get("theme_icon", "🗓️") in icons else 0)
            bg_color = st.color_picker("背景色", settings.get("theme_bg_color", "#ffffff"))
            text_color = st.color_picker("文字色", settings.get("theme_text_color", "#202124"))
            save_design = st.form_submit_button("デザインを保存")
        if save_design:
            with engine.begin() as conn:
                set_setting(conn, "theme_icon", icon)
                set_setting(conn, "theme_bg_color", bg_color)
                set_setting(conn, "theme_text_color", text_color)
            st.success("デザイン設定を保存しました。")
            st.rerun()

        st.divider()
        st.subheader("メンバー登録")
        with st.form("create_user_form", clear_on_submit=True):
            new_id = st.text_input("新しいユーザーID")
            new_name = st.text_input("表示名")
            new_password = st.text_input("初期パスワード（12文字以上推奨）", type="password")
            new_role = st.selectbox("権限", ["一般", "管理者"])
            create_user = st.form_submit_button("メンバーを登録")
        if create_user:
            new_id = new_id.strip()
            new_name = new_name.strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]{3,80}", new_id):
                st.error("ユーザーIDは英数字・_ . - の3〜80文字で入力してください。")
            elif not new_name or len(new_name) > 120:
                st.error("表示名を入力してください（120文字以内）。")
            elif len(new_password) < 12:
                st.error("初期パスワードは12文字以上にしてください。")
            elif get_user(new_id):
                st.error("そのユーザーIDはすでに存在します。")
            else:
                with engine.begin() as conn:
                    conn.execute(users_t.insert().values(
                        id=new_id, password_hash=password_hash(new_password), name=new_name,
                        role=new_role, active=True, totp_secret=None, created_at=now_jst()
                    ))
                st.success(f"{new_name} を登録しました。")
                st.rerun()

        st.divider()
        st.subheader("メンバー管理")
        for member in list_users():
            if member["id"] == OWNER_ID:
                continue
            col_a, col_b, col_c, col_d = st.columns([2, 2, 1, 2])
            col_a.write(f"**{member['name']}**")
            col_b.caption(member["id"])
            col_c.write(member["role"])
            if col_d.button("無効化" if member["active"] else "有効化", key=f"toggle_{member['id']}"):
                with engine.begin() as conn:
                    conn.execute(update(users_t).where(users_t.c.id == member["id"]).values(active=not member["active"]))
                st.rerun()
            with st.expander(f"{member['id']} の設定"):
                with st.form(f"edit_{member['id']}"):
                    edit_name = st.text_input("表示名", value=member["name"])
                    edit_role = st.selectbox("権限", ["一般", "管理者"], index=0 if member["role"] == "一般" else 1)
                    reset_pw = st.text_input("パスワード変更（変更する場合のみ入力）", type="password")
                    save_member = st.form_submit_button("変更を保存")
                if save_member:
                    if not edit_name.strip():
                        st.error("表示名を入力してください。")
                    elif reset_pw and len(reset_pw) < 12:
                        st.error("新しいパスワードは12文字以上にしてください。")
                    else:
                        values = {"name": edit_name.strip(), "role": edit_role}
                        if reset_pw:
                            values["password_hash"] = password_hash(reset_pw)
                        with engine.begin() as conn:
                            conn.execute(update(users_t).where(users_t.c.id == member["id"]).values(**values))
                        st.success("メンバー情報を更新しました。")
                        st.rerun()

        st.divider()
        st.subheader("データのエクスポート")
        if st.button("全活動履歴をCSVにする"):
            all_entries = get_entries()
            df = pd.DataFrame([{
                "日付": e["activity_date"].isoformat(), "担当ID": e["user_id"],
                "投稿日時": e["created_at"].strftime("%Y-%m-%d %H:%M:%S"), "活動内容": e["content"]
            } for e in all_entries])
            st.download_button("CSVをダウンロード", df.to_csv(index=False).encode("utf-8-sig"), "bsmgaming_all_activity.csv", "text/csv")

elif is_admin(user):
    with tabs[2]:
        st.header("🛠️ 管理者機能")
        st.caption("管理者は活動履歴を投稿し、担当メンバーを指定できます。アカウント管理・デザイン設定はオーナーのみ可能です。")
        members = list_users(active_only=True)
        if members:
            member_id = st.selectbox("メンバーの活動履歴を確認", [m["id"] for m in members], format_func=lambda x: next((m["name"] + "（" + m["id"] + "）" for m in members if m["id"] == x), x))
            records = get_entries(user_id=member_id)
            if records:
                df = pd.DataFrame([{
                    "日付": e["activity_date"].isoformat(),
                    "投稿日時": e["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
                    "活動内容": e["content"],
                } for e in records])
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("このメンバーの活動履歴はありません。")

st.caption("BSMGaming チーム管理システム")
