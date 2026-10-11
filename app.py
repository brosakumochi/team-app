import streamlit as st
import pandas as pd
import json
import os
import calendar
from datetime import datetime

# 保存先ファイルの設定
DATA_FILE = "team_management_data.json"

# --- 💾 データの読込・保存関数 ---
def load_data():
    default_users = [
        {"id": "BSMkuromu", "password": "BSMkuromu", "name": "オーナー", "role": "オーナー"},
        {"id": "koorogi", "password": "BSMkoorogi", "name": "koorogi", "role": "管理者"},
        {"id": "BSMmusasi", "password": "BSMmusasi", "name": "BSMmusasi", "role": "管理者"},
        {"id": "BSMgokiburi", "password": "BSMgokiburi", "name": "BSMgokiburi", "role": "管理者"},
    ]
    default_schedules = [
        {
            "日付": datetime.now().strftime("%Y-%m-%d"), 
            "担当ID": "BSMkuromu", 
            "活動内容": "システムアップデート：管理者が投稿時間・日時を追跡できるタイムスタンプ機能を実装完了",
            "投稿日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        },
    ]
    
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                st.session_state.users = data.get("users", default_users)
                st.session_state.schedules = data.get("schedules", default_schedules)
                st.session_state.theme_bg_color = data.get("theme_bg_color", "#ffffff")
                st.session_state.theme_text_color = data.get("theme_text_color", "#000000")
                st.session_state.theme_icon = data.get("theme_icon", "🗓️")
                st.session_state.update_mode = data.get("update_mode", False)
                st.session_state.update_start = data.get("update_start", "00:00")
                st.session_state.update_end = data.get("update_end", "00:00")
                return
        except Exception:
            pass

    st.session_state.users = default_users
    st.session_state.schedules = default_schedules
    st.session_state.theme_bg_color = "#ffffff"
    st.session_state.theme_text_color = "#000000"
    st.session_state.theme_icon = "🗓️"
    st.session_state.update_mode = False
    st.session_state.update_start = "01:00"
    st.session_state.update_end = "05:00"

def save_data():
    data = {
        "users": st.session_state.users,
        "schedules": st.session_state.schedules,
        "theme_bg_color": st.session_state.theme_bg_color,
        "theme_text_color": st.session_state.theme_text_color,
        "theme_icon": st.session_state.theme_icon,
        "update_mode": st.session_state.update_mode,
        "update_start": st.session_state.update_start,
        "update_end": st.session_state.update_end
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 1. ページ基本設定
st.set_page_config(page_title="チーム管理システム", layout="wide")

if "users" not in st.session_state:
    load_data()

# カレンダー選択用ステート
if "cal_year" not in st.session_state:
    st.session_state.cal_year = datetime.now().year
if "cal_month" not in st.session_state:
    st.session_state.cal_month = datetime.now().month
if "selected_date_str" not in st.session_state:
    st.session_state.selected_date_str = datetime.now().strftime("%Y-%m-%d")

# CSS調整
st.markdown(f"""
    <style>
    .stApp {{
        background-color: {st.session_state.theme_bg_color} !important;
        color: {st.session_state.theme_text_color} !important;
    }}
    h1, h2, h3, p, span, label {{
        color: {st.session_state.theme_text_color} !important;
    }}
    .custom-icon {{
        font-size: 48px;
        margin-bottom: 10px;
    }}
    </style>
    """, unsafe_allow_html=True)

if "logged_in_user" not in st.session_state:
    st.session_state.logged_in_user = None
if "fa_verified" not in st.session_state:
    st.session_state.fa_verified = False

def logout():
    st.session_state.logged_in_user = None
    st.session_state.fa_verified = False
    st.rerun()

user = st.session_state.logged_in_user
fa_verified = st.session_state.fa_verified

# --- 🔓 認証フロー ---
if not user:
    st.title("🔑 チーム管理システム - ログイン")
    input_id = st.text_input("ユーザーID")
    input_pw = st.text_input("パスワード", type="password")
    
    if st.button("ログイン"):
        matched_user = next((u for u in st.session_state.users if u["id"] == input_id and u["password"] == input_pw), None)
        if matched_user:
            if st.session_state.update_mode and matched_user["id"] != "BSMkuromu":
                st.error(f"⚠️ 現在アップデート期間中（{st.session_state.update_start} 〜 {st.session_state.update_end}）のため、ログインできません。")
            else:
                st.session_state.logged_in_user = matched_user
                if matched_user["id"] != "BSMkuromu":
                    st.session_state.fa_verified = True
                st.rerun()
        else:
            st.error("IDまたはパスワードが正しくありません。")

elif user and not fa_verified:
    st.title("🛡️ オーナー専用 二段階認証ロック")
    st.write(f"アカウント: **{user['name']} (ID: {user['id']})**")
    two_fa_input = st.text_input("2段階認証パスワードを入力してください", type="password")
    
    if st.button("認証する"):
        if two_fa_input == "20121107":
            st.session_state.fa_verified = True
            st.success("認証に成功しました。")
            st.rerun()
        else:
            st.error("二段階認証パスワードが正しくありません。")
            
    if st.button("キャンセルしてログイン画面に戻る"):
        logout()

else:
    # 🔓 メイン画面
    st.sidebar.title(f"👤 {user['name']} ({user['role']})")
    if st.sidebar.button("ログアウト"):
        logout()

    st.markdown(f'<div class="custom-icon">{st.session_state.theme_icon}</div>', unsafe_allow_html=True)

    # 👑 オーナー専用コントロールパネル
    if user["role"] == "オーナー":
        st.title("👑 オーナー専用コントロールパネル")
        
        # アップデートモード設定
        st.subheader("🔄 アップデートモード設定")
        is_update = st.checkbox("アップデートモードを有効化（kuromu以外のログイン・変更を禁止）", value=st.session_state.update_mode)
        col_start, col_end = st.columns(2)
        with col_start:
            time_start = st.text_input("開始時間（例: 01:00）", value=st.session_state.update_start)
        with col_end:
            time_end = st.text_input("終了時間（例: 05:00）", value=st.session_state.update_end)
            
        if st.button("アップデート設定を保存"):
            st.session_state.update_mode = is_update
            st.session_state.update_start = time_start
            st.session_state.update_end = time_end
            save_data()
            st.success("アップデート設定を更新しました。")
            st.rerun()
            
        st.divider()

        # デザイン変更設定
        st.subheader("🎨 アプリのデザイン変更（背景・文字・アイコン）")
        col_icon, col_bg, col_text = st.columns(3)
        with col_icon:
            current_icon = st.selectbox("アプリアイコンを選択", ["🗓️", "🚀", "🛡️", "👥", "🔥", "💻"], index=["🗓️", "🚀", "🛡️", "👥", "🔥", "💻"].index(st.session_state.theme_icon))
        with col_bg:
            current_bg = st.color_picker("背景色を選択", st.session_state.theme_bg_color)
        with col_text:
            current_text = st.color_picker("文字色を選択", st.session_state.theme_text_color)
            
        if st.button("デザインを適用する"):
            st.session_state.theme_icon = current_icon
            st.session_state.theme_bg_color = current_bg
            st.session_state.theme_text_color = current_text
            save_data()
            st.success("デザイン設定を保存しました。")
            st.rerun()
            
        st.divider()

        # 👥 ユーザー登録および削除機能
        st.subheader("👥 メンバーの管理（登録・削除）")
        col1, col2, col3, col4 = st.columns(4)
        with col1: new_id = st.text_input("新規ユーザーID")
        with col2: new_pw = st.text_input("新規パスワード", type="password")
        with col3: new_name = st.text_input("表示名")
        with col4: new_role = st.selectbox("権限レベル", ["一般", "管理者"])
        
        if st.button("メンバーを登録"):
            if new_id and new_pw and new_name:
                if any(u["id"] == new_id for u in st.session_state.users):
                    st.error("このIDは既に存在します。")
                else:
                    st.session_state.users.append({"id": new_id, "password": new_pw, "name": new_name, "role": new_role})
                    save_data()
                    st.success(f"「{new_name}」を登録しました。")
                    st.rerun()
            else:
                st.error("すべての項目を入力してください。")
                
        st.write("▼ 現在のメンバー一覧")
        for u in st.session_state.users:
            col_u_id, col_u_name, col_u_role, col_u_act = st.columns(4)
            with col_u_id: st.write(f"ID: {u['id']}")
            with col_u_name: st.write(f"名前: {u['name']}")
            with col_u_role: st.write(f"権限: {u['role']}")
            with col_u_act:
                if u["id"] == "BSMkuromu":
                    st.write("🔒 オーナーは削除不可")
                else:
                    if st.button("このメンバーを削除", key=f"del_user_{u['id']}"):
                        st.session_state.users.remove(u)
                        save_data()
                        st.success(f"ID: {u['id']} を削除しました。")
                        st.rerun()
        st.divider()

    # 🗓 カレンダーと活動内容の全体管理システム
    st.title("🗓️ チームスケジュール・活動履歴管理")
    
    if st.session_state.update_mode and user["role"] != "オーナー":
        st.warning(f"🛑 現在、緊急メンテナンス・アップデート期間中（{st.session_state.update_start} 〜 {st.session_state.update_end}）のため、新しい予定の追加や削除はできません。")
    else:
        col_calendar_view, col_entry_form = st.columns()
        
        # --- 🗺️ 左側：カレンダーUI ---
        with col_calendar_view:
            st.subheader("📅 カレンダービュー")
            
            col_m1, col_m2, col_m3 = st.columns()
            with col_m1:
                if st.button("◀ 前の月"):
                    st.session_state.cal_month -= 1
                    if st.session_state.cal_month == 0:
                        st.session_state.cal_month = 12
                        st.session_state.cal_year -= 1
                    st.rerun()
            with col_m2:
                st.markdown(f"<h3 style='text-align:center;'>{st.session_state.cal_year}年 {st.session_state.cal_month}月</h3>", unsafe_allow_html=True)
            with col_m3:
                if st.button("次の月 ▶"):

