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
        st.markdown("##### 📝 新增稽核題目")
        col_r, col_c, col_t, col_s = st.columns([3, 2, 4, 1])
        
        # 建立包含「套用所有職位」的選單
        options = ['【套用所有職位】'] + role_list
        q_roles = col_r.multiselect("適用職位 (可多選，或選套用所有)", options)
        
        q_category = col_c.text_input("大項目 (相同名稱會自動群組)")
        q_title = col_t.text_input("細項問題 (例如: 態度是否親切)")
        q_score = col_s.number_input("滿分", min_value=1, value=5)
        q_desc = st.text_input("問題說明 (選填)")
        
        if st.form_submit_button("新增題目"):
            # 判斷是否有選擇「套用所有職位」
            final_roles = role_list if '【套用所有職位】' in q_roles else q_roles
            
            if not final_roles or not q_category or not q_title:
                st.error("請完整填寫「適用職位」、「大項目」與「細項問題」！")
            else:
                for role in final_roles:
                    c.execute("INSERT INTO questions (role, category, title, description, max_score) VALUES (?, ?, ?, ?, ?)", (role, q_category, q_title, q_desc, q_score))
                conn.commit()
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
                st.markdown(f"### 👔 職位：{r}")
                
                for cat, cat_group in role_group.groupby('category'):
                    st.markdown(f"#### 📂 大項目：{cat}")
                    
                    for _, row in cat_group.iterrows():
                        col1, col2, col3, col4 = st.columns([3, 3, 2, 3])
                        
                        if st.session_state.edit_q_id == row['id']:
                            new_title = col1.text_input("修改問題", value=row['title'], key=f"edit_title_{row['id']}", label_visibility="collapsed")
                            new_desc = col2.text_input("修改說明", value=row['description'] if row['description'] else "", key=f"edit_desc_{row['id']}", label_visibility="collapsed")
                            new_score = col3.number_input("新滿分", min_value=1, value=row['max_score'], key=f"edit_val_{row['id']}", label_visibility="collapsed")
                            
                            c4_1, c4_2 = col4.columns(2)
                            if c4_1.button("✅ 確認", key=f"confirm_{row['id']}"):
                                c.execute("UPDATE questions SET title=?, description=?, max_score=? WHERE id=?", (new_title, new_desc, new_score, row['id']))
                                conn.commit()
                                st.session_state.edit_q_id = None
                                st.rerun()
                            if c4_2.button("❌ 取消", key=f"cancel_{row['id']}"):
                                st.session_state.edit_q_id = None
                                st.rerun()
                        else:
                            col1.write(f"**{row['title']}**")
                            col2.caption(row['description'] if row['description'] else "無說明")
                            col3.write(f"滿分: **{row['max_score']}**")
                            
                            c4_1, c4_2 = col4.columns(2)
                            if c4_1.button("✏️ 修改", key=f"edit_btn_{row['id']}"):
                                st.session_state.edit_q_id = row['id']
                                st.rerun()
                            if c4_2.button("🗑️ 刪除", key=f"del_q_{row['id']}"):
                                c.execute("DELETE FROM questions WHERE id=?", (row['id'],))
                                conn.commit()
                                st.rerun()
                    st.divider()

elif menu == "進行稽核":
    st.title("進行稽核作業")
    emps = c.execute("SELECT id, name, department, role, hourly_wage FROM employees").fetchall()
