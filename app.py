import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# ================= 1. 資料庫初始化 =================
conn = sqlite3.connect('audit_system.db', check_same_thread=False)
c = conn.cursor()

def init_db():
    c.execute('''CREATE TABLE IF NOT EXISTS roles (name TEXT PRIMARY KEY, is_hourly INTEGER, weight REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS employees (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, role TEXT, hourly_wage REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, category TEXT, title TEXT, description TEXT, max_score INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY AUTOINCREMENT, emp_id INTEGER, period TEXT, total_score INTEGER, wage_added REAL, status TEXT, timestamp TEXT)''')
    
    c.execute("SELECT COUNT(*) FROM roles")
    if c.fetchone()[0] == 0:
        default_roles = [('PT', 1, 0), ('正職', 0, 1), ('課級', 0, 2), ('部級', 0, 3)]
        c.executemany("INSERT INTO roles (name, is_hourly, weight) VALUES (?, ?, ?)", default_roles)
    conn.commit()

init_db()

# ================= 2. 側邊欄導覽 =================
st.set_page_config(page_title="稽核與獎金系統", layout="wide")
menu = st.sidebar.radio("系統導覽", ["進行稽核", "稽核紀錄", "獎金池分潤", "題庫設定", "員工與職位建檔"])
periods = ['2026-Q1', '2026-Q2', '2026-Q3', '2026-Q4']

# ================= 3. 功能模組 =================

if menu == "員工與職位建檔":
    st.title("員工與職位管理")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("1. 新增動態職位")
        with st.form("add_role_form"):
            new_role_name = st.text_input("職位名稱")
            is_hourly = st.checkbox("這是否為『時薪制』？(打勾代表用調薪邏輯，不打勾參與獎金池)")
            weight = st.number_input("獎金池權重 (時薪制請填0)", min_value=0.0, step=0.5, value=1.0)
            if st.form_submit_button("新增職位"):
                if new_role_name:
                    try:
                        c.execute("INSERT INTO roles (name, is_hourly, weight) VALUES (?, ?, ?)", (new_role_name, 1 if is_hourly else 0, weight))
                        conn.commit()
                        st.success(f"已新增職位：{new_role_name}")
                    except sqlite3.IntegrityError:
                        st.error("此職位已存在！")
        roles_df = pd.read_sql("SELECT name as 職稱, CASE WHEN is_hourly=1 THEN '是' ELSE '否' END as 時薪制, weight as 權重 FROM roles", conn)
        st.dataframe(roles_df, hide_index=True)

    with col2:
        st.subheader("2. 新增員工")
        role_list = [r[0] for r in c.execute("SELECT name FROM roles").fetchall()]
        with st.form("add_emp_form"):
            emp_name = st.text_input("員工姓名")
            emp_role = st.selectbox("選擇職位", role_list)
            emp_wage = st.number_input("當前時薪 (非時薪制請維持0)", min_value=0, step=5)
            if st.form_submit_button("新增員工"):
                c.execute("INSERT INTO employees (name, role, hourly_wage) VALUES (?, ?, ?)", (emp_name, emp_role, emp_wage))
                conn.commit()
                st.success(f"已新增員工：{emp_name}")
        emps_df = pd.read_sql("SELECT id, name as 姓名, role as 職位, hourly_wage as 時薪 FROM employees", conn)
        st.dataframe(emps_df, hide_index=True)

elif menu == "題庫設定":
    st.title("稽核題庫管理")
    role_list = [r[0] for r in c.execute("SELECT name FROM roles").fetchall()]
    with st.form("add_q_form"):
        col_r, col_c, col_t, col_s = st.columns([2, 2, 4, 1])
        q_role = col_r.selectbox("適用職位", role_list)
        q_category = col_c.text_input("大項目 (例如: 服儀)")
        q_title = col_t.text_input("細項問題 (例如: 頭髮是否整理)")
        q_score = col_s.number_input("滿分", min_value=1, value=5)
        q_desc = st.text_input("問題說明")
        if st.form_submit_button("新增題目"):
            c.execute("INSERT INTO questions (role, category, title, description, max_score) VALUES (?, ?, ?, ?, ?)", (q_role, q_category, q_title, q_desc, q_score))
            conn.commit()
            st.success("題目新增成功！")
    q_df = pd.read_sql("SELECT id, role as 職位, category as 大項, title as 問題, max_score as 滿分 FROM questions", conn)
    st.dataframe(q_df, hide_index=True)

elif menu == "進行稽核":
    st.title("進行稽核作業")
    emps = c.execute("SELECT id, name, role, hourly_wage FROM employees").fetchall()
    emp_dict = {f"{e[1]} ({e[2]})": e for e in emps}
    
    col1, col2 = st.columns(2)
    selected_emp_str = col1.selectbox("選擇員工", ["請選擇..."] + list(emp_dict.keys()))
    period = col2.selectbox("選擇期別", periods)
    
    if selected_emp_str != "請選擇...":
        emp_id, emp_name, emp_role, emp_wage = emp_dict[selected_emp_str]
        has_submitted = c.execute("SELECT id FROM audits WHERE emp_id=? AND period=? AND status='submitted'", (emp_id, period)).fetchone()
        
        if has_submitted:
            st.warning(f"⚠️ {emp_name} 在 {period} 已經有一筆送出的紀錄，若要重送請先至「稽核紀錄」撤回。")
        else:
            st.info(f"受測員工：**{emp_name}** | 職位：**{emp_role}**")
            questions = c.execute("SELECT id, category, title, description, max_score FROM questions WHERE role=?", (emp_role,)).fetchall()
            
            if not questions:
                st.error("此職位尚未建立題庫！請先至「題庫設定」新增。")
            else:
                with st.form("audit_form"):
                    scores = {}
                    df_q = pd.DataFrame(questions, columns=['id', 'category', 'title', 'description', 'max_score'])
                    for category, group in df_q.groupby('category'):
                        st.markdown(f"### {category}")
                        for _, row in group.iterrows():
                            options = list(range(row['max_score'] + 1))
                            scores[row['id']] = st.selectbox(f"{row['title']} (滿分 {row['max_score']} 分)", options, key=f"q_{row['id']}")
                            if row['description']: st.caption(row['description'])
                        st.markdown("---")
                        
                    if st.form_submit_button("送出稽核結果"):
                        total_score = sum(scores.values())
                        role_info = c.execute("SELECT is_hourly FROM roles WHERE name=?", (emp_role,)).fetchone()
                        is_hourly = role_info[0] if role_info else 0
                        
                        wage_added = 0
                        if is_hourly == 1:
                            if total_score >= 90: wage_added = 5
                            elif total_score >= 80: wage_added = 3
                            if wage_added > 0:
                                c.execute("UPDATE employees SET hourly_wage = hourly_wage + ? WHERE id = ?", (wage_added, emp_id))
                                
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("INSERT INTO audits (emp_id, period, total_score, wage_added, status, timestamp) VALUES (?, ?, ?, ?, ?, ?)", (emp_id, period, total_score, wage_added, 'submitted', timestamp))
                        conn.commit()
                        st.success(f"稽核已送出！總分：{total_score} 分。")
                        if wage_added > 0: st.success(f"達標！員工時薪已自動調升 {wage_added} 元。")
                        st.rerun()

elif menu == "稽核紀錄":
    st.title("稽核歷史紀錄")
    records = c.execute("SELECT a.id, a.period, e.name, e.role, a.total_score, a.wage_added, a.status, a.emp_id FROM audits a JOIN employees e ON a.emp_id = e.id ORDER BY a.id DESC").fetchall()
    
    for r in records:
        a_id, period, name, role, score, wage, status, emp_id = r
        with st.container():
            cols = st.columns([2, 2, 2, 2, 2])
            cols[0].write(f"**{period}**")
            cols[1].write(f"{name} ({role})")
            cols[2].write(f"總分: {score}")
            cols[3].write("✅ 已送出" if status == 'submitted' else "❌ 已撤回")
            if status == 'submitted' and cols[4].button("撤回紀錄", key=f"recall_{a_id}"):
                c.execute("UPDATE audits SET status='recalled' WHERE id=?", (a_id,))
                if wage > 0: c.execute("UPDATE employees SET hourly_wage = hourly_wage - ? WHERE id=?", (wage, emp_id))
                conn.commit()
                st.rerun()
            st.divider()

elif menu == "獎金池分潤":
    st.title("非時薪制（月薪/主管）獎金分潤結算")
    col1, col2 = st.columns(2)
    calc_period = col1.selectbox("結算期別", periods)
    bonus_pool = col2.number_input("本期總獎金池 (元)", min_value=0, value=10000, step=1000)
    
    if st.button("執行分潤計算"):
        query = '''SELECT e.name, e.role, a.total_score, r.weight FROM audits a JOIN employees e ON a.emp_id = e.id JOIN roles r ON e.role = r.name WHERE a.period = ? AND a.status = 'submitted' AND r.is_hourly = 0'''
        valid_audits = c.execute(query, (calc_period,)).fetchall()
        
        if not valid_audits:
            st.warning("本期尚未有任何符合條件的正職/主管稽核紀錄。")
        else:
            results = []
            total_final_weight = 0
            for row in valid_audits:
                name, role, score, weight = row
                final_weight = weight * (score / 100.0)
                total_final_weight += final_weight
                results.append({"姓名": name, "職位": role, "總分": score, "職位權重": weight, "最終計分": round(final_weight, 3)})
                
            if total_final_weight == 0:
                st.error("所有人的最終計分皆為0，無法分配獎金。")
            else:
                for r in results:
                    r["獲得獎金"] = int(round((r["最終計分"] / total_final_weight) * bonus_pool))
                st.success("結算完成！")
                st.dataframe(pd.DataFrame(results), use_container_width=True)
