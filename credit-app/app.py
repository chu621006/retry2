import streamlit as st
import pandas as pd
import io
import pdfplumber

# --- 1. GPA 轉換函數 ---
def parse_gpa_to_numeric(gpa_str):
    """
    Converts GPA string to a numeric value for comparison.
    This mapping can be adjusted based on specific grading scales.
    For this example, we define C- and above as passing.
    """
    gpa_map = {
        'A+': 4.3, 'A': 4.0, 'A-': 3.7,
        'B+': 3.3, 'B': 3.0, 'B-': 2.7,
        'C+': 2.3, 'C': 2.0, 'C-': 1.7,
        'D+': 1.3, 'D': 1.0, 'D-': 0.7,
        'E': 0.0, 'F': 0.0,
        '抵免': 999.0,
        '通過': 999.0
    }
    return gpa_map.get(gpa_str.strip(), 0.0)

# --- 2. 成績分析函數 ---
def analyze_student_grades(df):
    """
    Analyzes a DataFrame of student grades to calculate total earned credits
    and remaining credits for graduation.
    """
    GRADUATION_REQUIREMENT = 128

    df['學分'] = pd.to_numeric(df['學分'], errors='coerce').fillna(0)
    df['GPA_Numeric'] = df['GPA'].apply(parse_gpa_to_numeric)
    df['是否通過'] = df['GPA_Numeric'].apply(lambda x: x >= 1.7)
    passed_courses_df = df[df['是否通過'] & (df['學分'] > 0)].copy()

    total_earned_credits = passed_courses_df['學分'].sum()
    remaining_credits_to_graduate = max(0, GRADUATION_REQUIREMENT - total_earned_credits)

    return total_earned_credits, remaining_credits_to_graduate, passed_courses_df

# --- Streamlit 應用程式主體 ---
def main():
    st.title("總學分查詢系統 🎓")
    st.write("請上傳您的成績總表 PDF 檔案，系統將會為您查詢目前總學分與距離畢業所需的學分。")
    st.info("💡 確保您的成績單 PDF 是清晰的表格格式，以獲得最佳解析效果。")

    uploaded_file = st.file_uploader("上傳成績總表 PDF 檔案", type=["pdf"])

    if uploaded_file is not None:
        st.success("檔案上傳成功！正在分析中...")

        try:
            with pdfplumber.open(io.BytesIO(uploaded_file.getvalue())) as pdf:
                all_grades_data = []
                expected_columns_order = ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]

                for page in pdf.pages:
                    # 移除所有複雜的 table_settings，讓 pdfplumber 使用其默認的自適應提取
                    # 這樣可以避免 'Page' object has no attribute 'find_lines' 錯誤
                    tables = page.extract_tables()

                    for table in tables:
                        if not table:
                            continue

                        # 清理表頭
                        header = [col.replace('\n', ' ').strip() if col is not None else "" for col in table[0]] 
                        
                        # 建立一個映射，將提取到的列名映射到標準列名
                        col_mapping = {}
                        for i, h in enumerate(header):
                            if "學年度" in h: col_mapping[h] = "學年度"
                            elif "學期" in h: col_mapping[h] = "學期"
                            elif "選課代號" in h: col_mapping[h] = "選課代號"
                            elif "科目名稱" in h: col_mapping[h] = "科目名稱"
                            elif "學分" in h: col_mapping[h] = "學分"
                            elif "GPA" in h: col_mapping[h] = "GPA"
                            # 如果有其他列名，為其分配一個唯一的臨時名稱
                            else: col_mapping[h] = f"Unknown_Col_{i}" 

                        # 只有當我們識別出至少一個關鍵列時，才處理這個表格
                        if any(k in col_mapping.values() for k in ["學年度", "科目名稱", "學分", "GPA"]):
                            df_table = pd.DataFrame(table[1:]) # 數據從第二行開始
                            df_table.rename(columns=col_mapping, inplace=True) # 重命名列

                            # 確保所有預期列都存在
                            for col_name in expected_columns_order:
                                if col_name not in df_table.columns:
                                    df_table[col_name] = pd.NA
                                    
                            # 只保留預期列，並按正確順序排列
                            df_table = df_table[expected_columns_order]

                            # 進一步清理數據行的內容
                            for col in df_table.columns:
                                df_table[col] = df_table[col].astype(str).str.strip().str.replace('\n', ' ', regex=False).replace('None', pd.NA).replace('nan', pd.NA) # 也處理 'nan' 字串
                            
                            all_grades_data.append(df_table)
                
            if not all_grades_data:
                st.warning("未能從 PDF 中提取任何表格。請檢查 PDF 格式。") # 簡化錯誤訊息
                return

            full_grades_df = pd.concat(all_grades_data, ignore_index=True)

            # 數據清洗 (針對內容數據)
            full_grades_df.dropna(how='all', inplace=True) # 移除所有列都是 NaN 的行

            # 確保 '學年度' 是數字且篩選非成績行
            # 處理可能被識別為'nan'的學年度（雖然理論上不應該，但增加健壯性）
            full_grades_df = full_grades_df[
                full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$') | (full_grades_df['學年度'].astype(str) == 'nan') # Allow 'nan' for flexibility
            ]
            
            # 過濾掉勞作成績，即使科目名稱是 None 或 NaN 也不會出錯
            if '科目名稱' in full_grades_df.columns:
                full_grades_df = full_grades_df[~full_grades_df['科目名稱'].astype(str).str.contains('勞作成績', na=False)]
            
            # GPA 列清理
            full_grades_df['GPA'] = full_grades_df['GPA'].astype(str).str.strip()


            if not full_grades_df.empty:
                total_credits, remaining_credits, passed_courses_df = analyze_student_grades(full_grades_df)

                st.subheader("查詢結果 ✅")
                st.metric("目前總學分", total_credits)
                st.metric("距離畢業所需學分 (共128學分)", remaining_credits)

                st.subheader("通過的課程列表 📖")
                st.dataframe(passed_courses_df[['學年度', '學期', '科目名稱', '學分', 'GPA']])

                with st.expander("查看原始提取的數據 (用於除錯)"):
                    st.dataframe(full_grades_df)
            else:
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式。")

        except Exception as e:
            st.error(f"處理 PDF 檔案時發生錯誤：{e}")
            st.info("請確認您的 PDF 格式是否為清晰的表格。若問題持續，可能是 PDF 結構較為複雜，或者表格提取設定需要調整。")
            st.exception(e)

if __name__ == "__main__":
    main()
