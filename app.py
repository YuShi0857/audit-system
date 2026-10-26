import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import json
import io
import gspread
from google.oauth2.service_account import Credentials

# ================= 1. Google Sheets 與 資料庫初始化 =================
st.set_page_config(page_title="稽核與獎金系統", layout="wide")

# 設定 Google Sheets 連線
scope = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
creds = Credentials.from_service_account_info(json.loads(st.secrets["google_credentials"]), scopes=scope)
gc = gspread.authorize(creds)
sh = gc.open("稽核系統資料庫") # 確保你的試算表名稱與這裡一致

conn = sqlite3.connect('audit_system_cloud.db', check_same_thread=False)
c = conn.cursor()
tables = ["roles", "employees", "questions", "audits", "bonus_pools"]

# 初始化雲端試算表分頁與本地資料庫同步
@st.cache_resource
def sync_gsheets_to_local():
    for tab in tables:
        try:
            ws = sh.worksheet(tab)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=tab, rows="100", cols="20")
            
        data = ws.get_all_records()
        if data:
            df = pd.DataFrame(data)
            df.to_sql(tab, conn, if_exists='replace', index=False)
        else:
            # 若雲端是空的，建立空資料表
            if tab == "roles": c.execute('''CREATE TABLE IF NOT EXISTS roles (name TEXT PRIMARY KEY, department TEXT, is_hourly INTEGER, weight REAL)''')
            elif tab == "employees": c.execute('''CREATE TABLE IF NOT EXISTS employees (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, department TEXT, role TEXT, hourly_wage REAL)''')
            elif tab == "questions": c.execute('''CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, category TEXT, title TEXT, description TEXT, max_score INTEGER)''')
            elif tab == "audits": c.execute('''CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY AUTOINCREMENT, emp_id INTEGER, period TEXT, total_score INTEGER, wage_added REAL, status TEXT, timestamp TEXT, details TEXT)''')
            elif tab == "bonus_pools": c.execute('''CREATE TABLE IF NOT EXISTS bonus_pools (period TEXT, department TEXT, pool_amount INTEGER)''')
            conn.commit()

sync_gsheets_to_local()

# 自訂 Commit 函數：每次更新資料庫時，順便把該 Table 上傳回 Google Sheets
def cloud_commit(table_name):
    conn.commit()
    df = pd.read_sql(f"SELECT * FROM {table_name}", conn)
    ws = sh.worksheet(table_name)
    ws.clear()
    ws.update([df.columns.values.tolist()] + df.values.tolist())

# ================= 2. 系統設定與狀態初始化 =================
if 'edit_q_id' not in st.session_state: st.session_state.edit_q_id = None
if 'edit_emp_id' not in st.session_state: st.session_state.edit_emp_id = None
if 'edit_role_name' not in st.session_state: st.session_state.edit_role_name = None

current_year = datetime.now().year
periods = [f"{y}-Q{q}" for y in range(2026, current_year + 3) for q in range(1, 5)]

menu = st.sidebar.radio("系統導覽", ["進行稽核", "稽核紀錄 (分類與 Excel 匯出)", "部門獎金池分潤", "題庫設定", "員工與職位建檔"])

# ================= 3. 功能模組 =================

if menu == "員工與職位建檔":
    st.title("員工與職位管理")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("1. 新增職位")
        with st.form("add_role_form"):
            new_dept = st.text_input("所屬部門 (例如：黃金部門、操台部門)")
            new_role_name = st.text_input("職位名稱 (例如：行政PT)")
            is_hourly = st.checkbox("這是否為『時薪制』PT？(打勾代表用調薪邏輯，不參與獎金池)")
            weight = st.number_input("獎金池權重 (若為時薪PT請填0)", min_value=0.0, step=0.5, value=1.0)
            if st.form_submit_button("新增職位"):
                if new_dept and new_role_name:
                    try:
                        c.execute("INSERT INTO roles (name, department, is_hourly, weight) VALUES (?, ?, ?, ?)", (new_role_name, new_dept, 1 if is_hourly else 0, weight))
                        cloud_commit("roles")
                        st.success(f"已新增：{new_dept} - {new_role_name}")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("此職位已存在！")
                        
    with col2:
        st.subheader("2. 新增員工")
        role_list = [f"{r[0]} ({r[1]})" for r in c.execute("SELECT name, department FROM roles").fetchall()]
        with st.form("add_emp_form"):
            emp_name = st.text_input("員工姓名")
            emp_role_str = st.selectbox("選擇職位", role_list) if role_list else None
            emp_wage = st.number_input("當前時薪 (非PT請維持0)", min_value=0, step=5)
            if st.form_submit_button("新增員工") and emp_role_str:
                emp_role = emp_role_str.split(" (")[0]
                dept = c.execute("SELECT department FROM roles WHERE name=?", (emp_role,)).fetchone()[0]
                c.execute("INSERT INTO employees (name, department, role, hourly_wage) VALUES (?, ?, ?, ?)", (emp_name, dept, emp_role, emp_wage))
                cloud_commit("employees")
                st.success(f"已新增員工：{emp_name} ({dept})")
                st.rerun()

    st.markdown("---")
    tab_emps, tab_roles = st.tabs(["👥 現有員工清單 (修改/刪除)", "👔 現有職位清單 (修改/刪除)"])
    
    with tab_emps:
        st.subheader("員工資料管理")
        emps = c.execute("SELECT id, name, department, role, hourly_wage FROM employees ORDER BY department").fetchall()
        if not emps:
            st.info("尚無員工資料。")
        else:
            h1, h2, h3, h4, h5 = st.columns([2, 2, 3, 2, 2])
            h1.write("**姓名**")
            h2.write("**部門**")
            h3.write("**職位**")
            h4.write("**當前時薪**")
            h5.write("**操作**")
            st.divider()
            for emp in emps:
                e_id, e_name, e_dept, e_role, e_wage = emp
                c1, c2, c3, c4, c5 = st.columns([2, 2, 3, 2, 2])
                if st.session_state.edit_emp_id == e_id:
                    new_name = c1.text_input("姓名", value=e_name, key=f"e_name_{e_id}", label_visibility="collapsed")
                    role_options = [f"{r[0]} ({r[1]})" for r in c.execute("SELECT name, department FROM roles").fetchall()]
                    current_opt = f"{e_role} ({e_dept})"
                    idx = role_options.index(current_opt) if current_opt in role_options else 0
                    c2.markdown("*隨職位變動*")
                    new_role_str = c3.selectbox("職位", role_options, index=idx, key=f"e_role_{e_id}", label_visibility="collapsed")
                    new_wage = c4.number_input("時薪", min_value=0, value=int(e_wage), step=5, key=f"e_wage_{e_id}", label_visibility="collapsed")
                    c5a, c5b = c5.columns(2)
                    if c5a.button("✅", key=f"e_save_{e_id}"):
                        nr = new_role_str.split(" (")[0]
                        nd = c.execute("SELECT department FROM roles WHERE name=?", (nr,)).fetchone()[0]
                        c.execute("UPDATE employees SET name=?, department=?, role=?, hourly_wage=? WHERE id=?", (new_name, nd, nr, new_wage, e_id))
                        cloud_commit("employees")
                        st.session_state.edit_emp_id = None
                        st.rerun()
                    if c5b.button("❌", key=f"e_cancel_{e_id}"):
                        st.session_state.edit_emp_id = None
                        st.rerun()
                else:
                    c1.write(e_name)
                    c2.write(e_dept)
                    c3.write(e_role)
                    c4.write(e_wage)
                    c5a, c5b = c5.columns(2)
                    if c5a.button("✏️ 修改", key=f"e_edit_{e_id}"):
                        st.session_state.edit_emp_id = e_id
                        st.rerun()
                    if c5b.button("🗑️ 刪除", key=f"e_del_{e_id}"):
                        c.execute("DELETE FROM employees WHERE id=?", (e_id,))
                        cloud_commit("employees")
                        st.rerun()
                st.markdown("---")

    with tab_roles:
        st.subheader("職位資料管理")
        st.info("💡 提示：若修改職稱或部門名稱，系統會自動同步更新底下所有員工與題庫的對應標籤。")
        roles = c.execute("SELECT name, department, is_hourly, weight FROM roles ORDER BY department, weight DESC").fetchall()
        if roles:
            rh1, rh2, rh3, rh4, rh5 = st.columns([3, 3, 2, 2, 2])
            rh1.write("**所屬部門**")
            rh2.write("**職位名稱**")
            rh3.write("**時薪制PT**")
            rh4.write("**分潤權重**")
            rh5.write("**操作**")
            st.divider()
            for role_data in roles:
                r_name, r_dept, r_hourly, r_weight = role_data
                rc1, rc2, rc3, rc4, rc5 = st.columns([3, 3, 2, 2, 2])
                if st.session_state.edit_role_name == r_name:
                    new_dept = rc1.text_input("部門", value=r_dept, key=f"r_dept_{r_name}", label_visibility="collapsed")
                    new_name = rc2.text_input("職稱", value=r_name, key=f"r_name_{r_name}", label_visibility="collapsed")
                    new_hourly = rc3.checkbox("是", value=bool(r_hourly), key=f"r_hr_{r_name}")
                    new_weight = rc4.number_input("權重", min_value=0.0, value=float(r_weight), step=0.5, key=f"r_wt_{r_name}", label_visibility="collapsed")
                    rc5a, rc5b = rc5.columns(2)
                    if rc5a.button("✅", key=f"r_save_{r_name}"):
                        if new_name and new_dept:
                            try:
                                c.execute("UPDATE roles SET name=?, department=?, is_hourly=?, weight=? WHERE name=?", (new_name, new_dept, 1 if new_hourly else 0, new_weight, r_name))
                                if new_name != r_name or new_dept != r_dept:
                                    c.execute("UPDATE employees SET role=?, department=? WHERE role=?", (new_name, new_dept, r_name))
                                    cloud_commit("employees")
                                    c.execute("UPDATE questions SET role=? WHERE role=?", (new_name, r_name))
                                    cloud_commit("questions")
                                cloud_commit("roles")
                                st.session_state.edit_role_name = None
                                st.rerun()
                            except sqlite3.IntegrityError:
                                st.error("修改失敗：該職位名稱已存在！")
                    if rc5b.button("❌", key=f"r_cancel_{r_name}"):
                        st.session_state.edit_role_name = None
                        st.rerun()
                else:
                    rc1.write(r_dept)
                    rc2.write(r_name)
                    rc3.write("✅" if r_hourly else "❌")
                    rc4.write(r_weight)
                    rc5a, rc5b = rc5.columns(2)
                    if rc5a.button("✏️ 修改", key=f"r_edit_{r_name}"):
                        st.session_state.edit_role_name = r_name
                        st.rerun()
                    if rc5b.button("🗑️ 刪除", key=f"r_del_{r_name}"):
                        c.execute("DELETE FROM roles WHERE name=?", (r_name,))
                        cloud_commit("roles")
                        st.rerun()
                st.markdown("---")

elif menu == "題庫設定":
    st.title("稽核題庫管理")
    role_list = [r[0] for r in c.execute("SELECT name FROM roles").fetchall()]
    
    with st.form("add_q_form"):
        st.markdown("##### 📝 新增稽核題目")
        col_r, col_c, col_t, col_s = st.columns([3, 2, 4, 1])
        options = ['【套用所有職位】'] + role_list
        q_roles = col_r.multiselect("適用職位 (可多選，或選套用所有)", options)
        q_category = col_c.text_input("大項目 (相同名稱會自動群組)")
        q_title = col_t.text_input("細項問題 (例如: 態度是否親切)")
        q_score = col_s.number_input("滿分", min_value=1, value=5)
        q_desc = st.text_input("問題說明 (選填)")
        
        if st.form_submit_button("新增題目"):
            final_roles = role_list if '【套用所有職位】' in q_roles else q_roles
            if not final_roles or not q_category or not q_title:
                st.error("請完整填寫「適用職位」、「大項目」與「細項問題」！")
            else:
                for role in final_roles:
                    c.execute("INSERT INTO questions (role, category, title, description, max_score) VALUES (?, ?, ?, ?, ?)", (role, q_category, q_title, q_desc, q_score))
                cloud_commit("questions")
                st.success(f"題目新增成功！已同步套用至 {len(final_roles)} 個職位。")
                st.rerun()

    st.markdown("---")
    st.subheader("現有題庫清單 (支援修改內容、分數與刪除)")
    if not role_list:
        st.info("請先建立職位。")
    else:
        filter_role = st.selectbox("篩選檢視職位", ["全部"] + role_list)
        query = "SELECT id, role, category, title, description, max_score FROM questions"
        params = []
        if filter_role != "全部":
            query += " WHERE role = ?"
            params.append(filter_role)
        query += " ORDER BY role, category"
        questions = c.execute(query, params).fetchall()
        
        if not questions:
            st.info("此職位尚無題目資料。")
        else:
            df_q = pd.DataFrame(questions, columns=['id', 'role', 'category', 'title', 'description', 'max_score'])
            for r, role_group in df_q.groupby('role'):
                role_total_score = int(role_group['max_score'].sum())
                if role_total_score > 100: st.markdown(f"### 👔 職位：{r} | 總分：:red[{role_total_score} / 100] ⚠️已超標")
                else: st.markdown(f"### 👔 職位：{r} | 總分：:green[{role_total_score} / 100]")
                
                for cat, cat_group in role_group.groupby('category'):
                    cat_total_score = int(cat_group['max_score'].sum())
                    st.markdown(f"#### 📂 大項目：{cat} *(小計：{cat_total_score} 分)*")
                    for _, row in cat_group.iterrows():
                        col1, col2, col3, col4 = st.columns([3, 3, 2, 3])
                        if st.session_state.edit_q_id == row['id']:
                            new_title = col1.text_input("修改", value=row['title'], key=f"et_{row['id']}", label_visibility="collapsed")
                            new_desc = col2.text_input("說明", value=row['description'] if row['description'] else "", key=f"ed_{row['id']}", label_visibility="collapsed")
                            new_score = col3.number_input("分", min_value=1, value=row['max_score'], key=f"ev_{row['id']}", label_visibility="collapsed")
                            c4_1, c4_2 = col4.columns(2)
                            if c4_1.button("✅", key=f"c_{row['id']}"):
                                c.execute("UPDATE questions SET title=?, description=?, max_score=? WHERE id=?", (new_title, new_desc, new_score, row['id']))
                                cloud_commit("questions")
                                st.session_state.edit_q_id = None
                                st.rerun()
                            if c4_2.button("❌", key=f"x_{row['id']}"):
                                st.session_state.edit_q_id = None
                                st.rerun()
                        else:
                            col1.write(f"**{row['title']}**")
                            col2.caption(row['description'] if row['description'] else "無說明")
                            col3.write(f"滿分: **{row['max_score']}**")
                            c4_1, c4_2 = col4.columns(2)
                            if c4_1.button("✏️ 修改", key=f"eb_{row['id']}"):
                                st.session_state.edit_q_id = row['id']
                                st.rerun()
                            if c4_2.button("🗑️ 刪除", key=f"dq_{row['id']}"):
                                c.execute("DELETE FROM questions WHERE id=?", (row['id'],))
                                cloud_commit("questions")
                                st.rerun()
                    st.divider()

elif menu == "進行稽核":
    st.title("進行稽核作業")
    emps = c.execute("SELECT id, name, department, role, hourly_wage FROM employees").fetchall()
    emp_dict = {f"{e[1]} - {e[2]} {e[3]}": e for e in emps}
    
    col1, col2 = st.columns(2)
    selected_emp_str = col1.selectbox("選擇受測員工", ["請選擇..."] + list(emp_dict.keys()))
    period = col2.selectbox("選擇期別", periods)
    
    if selected_emp_str != "請選擇...":
        emp_id, emp_name, emp_dept, emp_role, emp_wage = emp_dict[selected_emp_str]
        has_submitted = c.execute("SELECT id FROM audits WHERE emp_id=? AND period=? AND status='submitted'", (emp_id, period)).fetchone()
        
        if has_submitted:
            st.warning(f"⚠️ {emp_name} 在 {period} 已經有一筆送出的紀錄，若要重送請先至「稽核紀錄」撤回。")
        else:
            st.info(f"受測員工：**{emp_name}** | 部門：**{emp_dept}** | 職位：**{emp_role}**")
            questions = c.execute("SELECT id, category, title, description, max_score FROM questions WHERE role=?", (emp_role,)).fetchall()
            
            if not questions:
                st.error("此職位尚未建立題庫！請先至「題庫設定」新增專屬題目。")
            else:
                with st.form("audit_form"):
                    scores_data = {}
                    df_q = pd.DataFrame(questions, columns=['id', 'category', 'title', 'description', 'max_score'])
                    
                    for category, group in df_q.groupby('category'):
                        st.markdown(f"### 📂 {category}")
                        for _, row in group.iterrows():
                            st.markdown(f"**{row['title']}** (滿分 {row['max_score']} 分)")
                            if row['description']: st.caption(f"說明: {row['description']}")
                            col_s, col_c = st.columns([1, 3])
                            s_val = col_s.selectbox("評分", list(range(row['max_score'] + 1)), key=f"q_{row['id']}")
                            c_val = col_c.text_input("原因/備註闡述", value="無", key=f"c_{row['id']}")
                            scores_data[row['id']] = {'category': category, 'title': row['title'], 'score': s_val, 'comment': c_val}
                        st.markdown("---")
                    
                    st.markdown("### 🌟 額外加分 (彈性)")
                    col_b1, col_b2 = st.columns([1, 3])
                    bonus_score = col_b1.number_input("加分分數 (若無請維持 0)", min_value=0, value=0, step=1)
                    bonus_reason = col_b2.text_input("加分事蹟/原因 (若有給分請務必填寫)")
                    st.markdown("---")
                        
                    if st.form_submit_button("確認並送出稽核結果"):
                        if bonus_score > 0 and not bonus_reason.strip():
                            st.error("❌ 若有給予額外加分，請務必填寫旁邊的「加分事蹟/原因」！")
                        else:
                            total_score = sum([d['score'] for d in scores_data.values()]) + bonus_score
                            role_info = c.execute("SELECT is_hourly FROM roles WHERE name=?", (emp_role,)).fetchone()
                            is_hourly = role_info[0] if role_info else 0
                            
                            old_wage = emp_wage
                            new_wage = old_wage
                            wage_added = 0
                            
                            if is_hourly == 1:
                                if total_score >= 90: wage_added = 5
                                elif total_score >= 80: wage_added = 3
                                if wage_added > 0:
                                    new_wage = old_wage + wage_added
                                    c.execute("UPDATE employees SET hourly_wage = ? WHERE id = ?", (new_wage, emp_id))
                                    cloud_commit("employees")
                            
                            if bonus_score > 0:
                                scores_data['extra_bonus'] = {'category': '🌟 額外加分', 'title': '主管彈性表現加分', 'score': bonus_score, 'comment': bonus_reason}
                            
                            scores_data['wage_info'] = {'old': old_wage, 'new': new_wage}
                            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            details_json = json.dumps(scores_data, ensure_ascii=False)
                            
                            c.execute("INSERT INTO audits (emp_id, period, total_score, wage_added, status, timestamp, details) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                      (emp_id, period, total_score, wage_added, 'submitted', timestamp, details_json))
                            cloud_commit("audits")
                            st.success(f"稽核已送出！含額外加分共計：{total_score} 分。")
                            if wage_added > 0: st.success(f"🎉 達標！該 PT 員工時薪已自動調升 {wage_added} 元。")
                            st.rerun()

elif menu == "稽核紀錄 (分類與 Excel 匯出)":
    st.title("稽核歷史紀錄與 Excel 報表匯出")
    
    records = c.execute('''
        SELECT a.id, a.period, e.name, e.department, e.role, a.total_score, a.wage_added, a.status, a.emp_id, a.timestamp, a.details, r.is_hourly, r.weight
        FROM audits a JOIN employees e ON a.emp_id = e.id JOIN roles r ON e.role = r.name
        WHERE a.status = 'submitted'
        ORDER BY a.period DESC, e.department, r.weight DESC, a.total_score DESC
    ''').fetchall()
    
    if not records:
        st.info("目前尚無任何已送出的稽核紀錄。")
    else:
        summary_data = []
        detail_data = []
        
        pools = c.execute("SELECT period, department, pool_amount FROM bonus_pools").fetchall()
        pool_dict = {f"{p[0]}_{p[1]}": p[2] for p in pools}
        
        period_dept_total_weights = {}
        for r in records:
            p, dept, is_hourly, score, weight = r[1], r[3], r[11], r[5], r[12]
            if is_hourly == 0:
                key = f"{p}_{dept}"
                final_w = weight * (score / 100.0)
                period_dept_total_weights[key] = period_dept_total_weights.get(key, 0) + final_w
                
        unique_periods = sorted(list(set([r[1] for r in records])), reverse=True)
        
        for up in unique_periods:
            with st.expander(f"📁 展開期別：{up}", expanded=False):
                st.markdown(f"#### 📅 {up} 結算結果")
                
                period_records = [r for r in records if r[1] == up]
                for r in period_records:
                    a_id, p, name, dept, role, score, wage_added, status, emp_id, timestamp, details_json, is_hourly, weight = r
                    
                    details_dict = json.loads(details_json) if details_json else {}
                    wage_info = details_dict.get('wage_info', {})
                    old_wage = wage_info.get('old', '無資料')
                    new_wage = wage_info.get('new', '無資料')
                    
                    bonus_str = "不適用"
                    bonus_val = 0
                    if is_hourly == 0:
                        pool_key = f"{p}_{dept}"
                        if pool_key in pool_dict and period_dept_total_weights.get(pool_key, 0) > 0:
                            my_w = weight * (score / 100.0)
                            bonus_val = int(round((my_w / period_dept_total_weights[pool_key]) * pool_dict[pool_key]))
                            bonus_str = f"💰 {bonus_val} 元"
                        else:
                            bonus_str = "*(尚未結算獎金池)*"
                    else:
                        bonus_str = f"時薪調整: {old_wage} ➔ {new_wage}"
                    
                    summary_data.append({
                        "期別": p, "部門": dept, "職位": role, "姓名": name, "類型": "PT" if is_hourly else "正職/主管",
                        "稽核總分": score, "調整前時薪": old_wage if is_hourly else "-", "調整後時薪": new_wage if is_hourly else "-",
                        "分發獎金": bonus_val if not is_hourly else "-"
                    })
                    
                    with st.expander(f"👤 {dept} - {role}：{name} | 總分: {score} | {bonus_str}"):
                        st.write(f"**送單時間：** {timestamp}")
                        
                        detail_list = []
                        for q_id, q_data in details_dict.items():
                            if q_id == 'wage_info': continue
                            c_name = q_data.get('category', '-')
                            t_name = q_data.get('title', '-')
                            s_val = q_data.get('score', 0)
                            comment = q_data.get('comment', '無')
                            
                            detail_list.append({"大項目": c_name, "細項問題": t_name, "得分": s_val, "備註/原因": comment})
                            detail_data.append({
                                "期別": p, "部門": dept, "職位": role, "姓名": name,
                                "大項目": c_name, "細項問題": t_name, "得分": s_val, "備註/原因": comment
                            })
                        st.table(pd.DataFrame(detail_list))
                        
                        if st.button("撤回此紀錄", key=f"recall_{a_id}"):
                            c.execute("UPDATE audits SET status='recalled' WHERE id=?", (a_id,))
                            cloud_commit("audits")
                            if is_hourly == 1 and wage_added > 0: 
                                c.execute("UPDATE employees SET hourly_wage = hourly_wage - ? WHERE id=?", (wage_added, emp_id))
                                cloud_commit("employees")
                            st.rerun()

        st.markdown("---")
        st.markdown("### 📥 下載完整 Excel 報表")
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            pd.DataFrame(summary_data).to_excel(writer, sheet_name='稽核總表與結算金額', index=False)
            pd.DataFrame(detail_data).to_excel(writer, sheet_name='評分細項展開明細', index=False)
        excel_data = output.getvalue()
        
        st.download_button(
            label="點此下載 Excel 檔 (含分類總表與明細)",
            data=excel_data,
            file_name=f"內部稽核與獎金報表_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

elif menu == "部門獎金池分潤":
    st.title("部門獨立獎金分潤結算 (限正職/主管)")
    departments = [r[0] for r in c.execute("SELECT DISTINCT department FROM roles").fetchall()]
    
    col1, col2, col3 = st.columns(3)
    calc_period = col1.selectbox("結算期別", periods)
    calc_dept = col2.selectbox("要結算的部門", departments) if departments else None
    bonus_pool = col3.number_input("該部門本期總獎金池 (元)", min_value=0, value=10000, step=1000)
    
    if st.button("執行分潤計算並紀錄") and calc_dept:
        query = '''
            SELECT e.name, e.role, a.total_score, r.weight 
            FROM audits a JOIN employees e ON a.emp_id = e.id JOIN roles r ON e.role = r.name 
            WHERE a.period = ? AND a.status = 'submitted' AND r.is_hourly = 0 AND e.department = ?
        '''
        valid_audits = c.execute(query, (calc_period, calc_dept)).fetchall()
        
        if not valid_audits:
            st.warning(f"本期【{calc_dept}】尚未有任何符合條件的正職/主管稽核紀錄。")
        else:
            c.execute("DELETE FROM bonus_pools WHERE period=? AND department=?", (calc_period, calc_dept))
            c.execute("INSERT INTO bonus_pools (period, department, pool_amount) VALUES (?, ?, ?)", (calc_period, calc_dept, bonus_pool))
            cloud_commit("bonus_pools")
            
            results = []
            total_final_weight = 0
            for row in valid_audits:
                name, role, score, weight = row
                final_weight = weight * (score / 100.0)
                total_final_weight += final_weight
                results.append({"姓名": name, "職位": role, "總分": score, "原設定權重": weight, "最終計分": round(final_weight, 3)})
                
            if total_final_weight == 0:
                st.error("所有人的最終計分皆為0，無法分配獎金。")
            else:
                for r in results:
                    r["獲得獎金"] = int(round((r["最終計分"] / total_final_weight) * bonus_pool))
                st.success(f"【{calc_dept}】結算完成！結果已同步至「稽核紀錄」。")
                st.dataframe(pd.DataFrame(results), use_container_width=True)
