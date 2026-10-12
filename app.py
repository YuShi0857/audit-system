import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import json

# ================= 1. 資料庫初始化 =================
conn = sqlite3.connect('audit_system_v3.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute('''CREATE TABLE IF NOT EXISTS roles (name TEXT PRIMARY KEY, department TEXT, is_hourly INTEGER, weight REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS employees (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, department TEXT, role TEXT, hourly_wage REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, category TEXT, title TEXT, description TEXT, max_score INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY AUTOINCREMENT, emp_id INTEGER, period TEXT, total_score INTEGER, wage_added REAL, status TEXT, timestamp TEXT, details TEXT)''')
    
    c.execute("SELECT COUNT(*) FROM roles")
    if c.fetchone()[0] == 0:
        default_roles = [
            ('黃金PT', '黃金部門', 1, 0),
            ('黃金正職', '黃金部門', 0, 3),
            ('黃金主播', '黃金部門', 0, 2),
            ('操台PT', '操台部門', 1, 0),
            ('操台正職', '操台部門', 0, 1),
            ('操台課級', '操台部門', 0, 2),
            ('操台部級', '操台部門', 0, 3)
        ]
        c.executemany("INSERT INTO roles (name, department, is_hourly, weight) VALUES (?, ?, ?, ?)", default_roles)
    conn.commit()

init_db()

# ================= 2. 系統設定與狀態初始化 =================
st.set_page_config(page_title="稽核與獎金系統", layout="wide")

# 初始化修改題目的狀態變數 (防呆用)
if 'edit_q_id' not in st.session_state:
    st.session_state.edit_q_id = None

current_year = datetime.now().year
periods = [f"{y}-Q{q}" for y in range(2026, current_year + 3) for q in range(1, 5)]

menu = st.sidebar.radio("系統導覽", ["進行稽核", "稽核紀錄 (含篩選與明細)", "部門獎金池分潤", "題庫設定", "員工與職位建檔"])

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
                        conn.commit()
                        st.success(f"已新增：{new_dept} - {new_role_name}")
                    except sqlite3.IntegrityError:
                        st.error("此職位已存在！")
        
        roles_df = pd.read_sql("SELECT department as 部門, name as 職稱, CASE WHEN is_hourly=1 THEN '是' ELSE '否' END as 時薪制, weight as 分潤權重 FROM roles ORDER BY department, weight DESC", conn)
        st.dataframe(roles_df, hide_index=True)

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
                conn.commit()
                st.success(f"已新增員工：{emp_name} ({dept})")
                
        emps_df = pd.read_sql("SELECT id, name as 姓名, department as 部門, role as 職位, hourly_wage as 時薪 FROM employees ORDER BY department", conn)
        st.dataframe(emps_df, hide_index=True)

elif menu == "題庫設定":
    st.title("稽核題庫管理")
    role_list = [r[0] for r in c.execute("SELECT name FROM roles").fetchall()]
    
    with st.form("add_q_form"):
        col_r, col_c, col_t, col_s = st.columns([2, 2, 4, 1])
        q_role = col_r.selectbox("適用職位", role_list) if role_list else None
        q_category = col_c.text_input("大項目 (相同的名稱會自動群組在一起)")
        q_title = col_t.text_input("細項問題 (例如: 態度是否親切)")
        q_score = col_s.number_input("滿分", min_value=1, value=5)
        q_desc = st.text_input("問題說明 (選填)")
        
        if st.form_submit_button("新增題目"):
            if not q_role or not q_category or not q_title:
                st.error("請完整填寫「大項目」與「細項問題」！")
            else:
                c.execute("INSERT INTO questions (role, category, title, description, max_score) VALUES (?, ?, ?, ?, ?)", (q_role, q_category, q_title, q_desc, q_score))
                conn.commit()
                st.success("題目新增成功！")
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
                st.markdown(f"### 👔 職位：{r}")
                
                for cat, cat_group in role_group.groupby('category'):
                    st.markdown(f"#### 📂 大項目：{cat}")
                    
                    for _, row in cat_group.iterrows():
                        col1, col2, col3, col4 = st.columns([3, 3, 2, 3])
                        
                        # 【修改與防呆邏輯】判斷目前這題是否在「編輯模式」
                        if st.session_state.edit_q_id == row['id']:
                            # 編輯模式：顯示三個輸入框與確認/取消按鈕
                            new_title = col1.text_input("修改問題", value=row['title'], key=f"edit_title_{row['id']}", label_visibility="collapsed")
                            new_desc = col2.text_input("修改說明", value=row['description'] if row['description'] else "", key=f"edit_desc_{row['id']}", label_visibility="collapsed")
                            new_score = col3.number_input("新滿分", min_value=1, value=row['max_score'], key=f"edit_val_{row['id']}", label_visibility="collapsed")
                            
                            c4_1, c4_2 = col4.columns(2)
                            if c4_1.button("✅ 確認", key=f"confirm_{row['id']}"):
                                c.execute("UPDATE questions SET title=?, description=?, max_score=? WHERE id=?", (new_title, new_desc, new_score, row['id']))
                                conn.commit()
                                st.session_state.edit_q_id = None # 解除編輯模式
                                st.rerun()
                            if c4_2.button("❌ 取消", key=f"cancel_{row['id']}"):
                                st.session_state.edit_q_id = None # 解除編輯模式
                                st.rerun()
                        else:
                            # 正常模式：顯示文字與修改/刪除按鈕
                            col1.write(f"**{row['title']}**")
                            col2.caption(row['description'] if row['description'] else "無說明")
                            col3.write(f"滿分: **{row['max_score']}**")
                            
                            c4_1, c4_2 = col4.columns(2)
                            if c4_1.button("✏️ 修改", key=f"edit_btn_{row['id']}"):
                                st.session_state.edit_q_id = row['id'] # 進入編輯模式
                                st.rerun()
                            if c4_2.button("🗑️ 刪除", key=f"del_q_{row['id']}"):
                                c.execute("DELETE FROM questions WHERE id=?", (row['id'],))
                                conn.commit()
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
                            
                            scores_data[row['id']] = {
                                'category': category,
                                'title': row['title'],
                                'score': s_val,
                                'comment': c_val
                            }
                        st.markdown("---")
                        
                    if st.form_submit_button("確認並送出稽核結果"):
                        total_score = sum([d['score'] for d in scores_data.values()])
                        role_info = c.execute("SELECT is_hourly FROM roles WHERE name=?", (emp_role,)).fetchone()
                        is_hourly = role_info[0] if role_info else 0
                        
                        wage_added = 0
                        if is_hourly == 1:
                            if total_score >= 90: wage_added = 5
                            elif total_score >= 80: wage_added = 3
                            if wage_added > 0:
                                c.execute("UPDATE employees SET hourly_wage = hourly_wage + ? WHERE id = ?", (wage_added, emp_id))
                                
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        details_json = json.dumps(scores_data, ensure_ascii=False)
                        
                        c.execute("INSERT INTO audits (emp_id, period, total_score, wage_added, status, timestamp, details) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                  (emp_id, period, total_score, wage_added, 'submitted', timestamp, details_json))
                        conn.commit()
                        st.success(f"稽核已送出！總分：{total_score} 分。")
                        if wage_added > 0: st.success(f"🎉 達標！該 PT 員工時薪已自動調升 {wage_added} 元。")
                        st.rerun()

elif menu == "稽核紀錄 (含篩選與明細)":
    st.title("稽核歷史紀錄與明細查詢")
    
    records = c.execute('''
        SELECT a.id, a.period, e.name, e.department, e.role, a.total_score, a.wage_added, a.status, a.emp_id, a.timestamp, a.details 
        FROM audits a JOIN employees e ON a.emp_id = e.id ORDER BY a.id DESC
    ''').fetchall()
    
    if not records:
        st.info("目前尚無任何稽核紀錄。")
    else:
        df_records = pd.DataFrame(records, columns=['id', 'period', 'name', 'department', 'role', 'score', 'wage_added', 'status', 'emp_id', 'timestamp', 'details'])
        
        st.markdown("##### 🔍 條件篩選")
        f_col1, f_col2, f_col3 = st.columns(3)
        filter_period = f_col1.selectbox("依期別篩選", ["全部"] + list(df_records['period'].unique()))
        filter_role = f_col2.selectbox("依職位篩選", ["全部"] + list(df_records['role'].unique()))
        filter_name = f_col3.selectbox("依姓名篩選", ["全部"] + list(df_records['name'].unique()))
        
        filtered_df = df_records.copy()
        if filter_period != "全部": filtered_df = filtered_df[filtered_df['period'] == filter_period]
        if filter_role != "全部": filtered_df = filtered_df[filtered_df['role'] == filter_role]
        if filter_name != "全部": filtered_df = filtered_df[filtered_df['name'] == filter_name]
        
        st.markdown("---")
        st.markdown(f"共找到 **{len(filtered_df)}** 筆紀錄：")
        
        for _, row in filtered_df.iterrows():
            status_icon = "✅ 已送出" if row['status'] == 'submitted' else "❌ 已撤回"
            expander_title = f"{row['period']} | {row['department']} - {row['role']} : {row['name']} | 總分: {row['score']} ({status_icon})"
            
            with st.expander(expander_title):
                st.write(f"**送單時間：** {row['timestamp']}")
                if row['wage_added'] > 0:
                    st.success(f"💰 此期 PT 時薪調漲: +{row['wage_added']} 元")
                
                if row['details']:
                    st.markdown("#### 📝 稽核明細")
                    details_dict = json.loads(row['details'])
                    detail_list = []
                    for q_id, q_data in details_dict.items():
                        detail_list.append({
                            "大項目": q_data.get('category', '-'),
                            "細項問題": q_data.get('title', '-'),
                            "得分": q_data.get('score', 0),
                            "備註/原因": q_data.get('comment', '無')
                        })
                    st.table(pd.DataFrame(detail_list))
                
                if row['status'] == 'submitted' and st.button("撤回此紀錄", key=f"recall_{row['id']}"):
                    c.execute("UPDATE audits SET status='recalled' WHERE id=?", (row['id'],))
                    if row['wage_added'] > 0: 
                        c.execute("UPDATE employees SET hourly_wage = hourly_wage - ? WHERE id=?", (row['wage_added'], row['emp_id']))
                    conn.commit()
                    st.rerun()

elif menu == "部門獎金池分潤":
    st.title("部門獨立獎金分潤結算 (限正職/主管)")
    departments = [r[0] for r in c.execute("SELECT DISTINCT department FROM roles").fetchall()]
    
    col1, col2, col3 = st.columns(3)
    calc_period = col1.selectbox("結算期別", periods)
    calc_dept = col2.selectbox("要結算的部門", departments) if departments else None
    bonus_pool = col3.number_input("該部門本期總獎金池 (元)", min_value=0, value=10000, step=1000)
    
    if st.button("執行分潤計算") and calc_dept:
        query = '''
            SELECT e.name, e.role, a.total_score, r.weight 
            FROM audits a 
            JOIN employees e ON a.emp_id = e.id 
            JOIN roles r ON e.role = r.name 
            WHERE a.period = ? AND a.status = 'submitted' AND r.is_hourly = 0 AND e.department = ?
        '''
        valid_audits = c.execute(query, (calc_period, calc_dept)).fetchall()
        
        if not valid_audits:
            st.warning(f"本期【{calc_dept}】尚未有任何符合條件的正職/主管稽核紀錄。")
        else:
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
                st.success(f"【{calc_dept}】結算完成！")
                st.dataframe(pd.DataFrame(results), use_container_width=True)
