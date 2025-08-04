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
                # 定義預期的列名順序，以在合併前進行檢查和重命名
                expected_columns_order = ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]

                for page in pdf.pages:
                    tables = page.extract_tables()

                    for table in tables:
                        # 確保表格不為空，並且包含足夠的列
                        if table and len(table[0]) >= len(expected_columns_order):
                            header = [col.replace('\n', ' ').strip() for col in table[0]] # 清理頭部列名
                            
                            # 檢查清理後的列名是否包含所有預期列，並且順序大致匹配
                            # 或者至少 '學年度' 存在於第一個位置，表示這是一個成績表格
                            if header[0] == "學年度":
                                df_table = pd.DataFrame(table[1:], columns=header)
                                
                                # 再次清理 DataFrame 的列名，確保它們是我們想要的標準名稱
                                # 這一步很關鍵，用於處理 pdfplumber 可能返回的非標準列名
                                cleaned_cols = {}
                                for col in df_table.columns:
                                    cleaned_col_name = col.replace('\n', ' ').strip()
                                    if cleaned_col_name in expected_columns_order:
                                        cleaned_cols[col] = cleaned_col_name
                                df_table.rename(columns=cleaned_cols, inplace=True)

                                # 確保 DataFrame 有所有預期的列，如果缺失則添加並填充 NaN
                                for col_name in expected_columns_order:
                                    if col_name not in df_table.columns:
                                        df_table[col_name] = pd.NA # 或者 ''
                                        
                                # 只保留我們關心的列，並按預期順序排列
                                df_table = df_table[expected_columns_order]
                                
                                all_grades_data.append(df_table)

            if not all_grades_data:
                st.warning("未能從 PDF 中提取任何表格。請檢查 PDF 格式或嘗試調整解析參數。")
                return

            full_grades_df = pd.concat(all_grades_data, ignore_index=True)

            # 數據清洗 (針對內容數據)
            full_grades_df.dropna(how='all', inplace=True) # 移除所有列都是 NaN 的行
            for col in full_grades_df.columns:
                if col in ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]:
                    full_grades_df[col] = full_grades_df[col].astype(str).str.strip().str.replace('\n', ' ', regex=False)
            
            # 過濾掉那些明顯不是成績行的資料
            # 這裡的錯誤就是因為 '科目名稱' 列不存在
            # 確保 '科目名稱' 存在於 DataFrame 且值不為 NaN 或 None
            if '科目名稱' in full_grades_df.columns:
                full_grades_df = full_grades_df[
                    full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$') &
                    ~full_grades_df['科目名稱'].astype(str).str.contains('勞作成績', na=False)
                ]
            else:
                st.warning("提取的數據中未找到 '科目名稱' 列，可能導致分析不準確。")
                # 如果沒有 '科目名稱' 列，則跳過此篩選，但可能會包含勞作成績行
                full_grades_df = full_grades_df[full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$')]

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
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式或嘗試調整解析參數。")

        except Exception as e:
            st.error(f"處理 PDF 檔案時發生錯誤：{e}")
            st.info("請確認您的 PDF 格式是否為清晰的表格。若問題持續，可能是 PDF 結構較為複雜，需要調整 `pdfplumber` 的表格提取設定。")
            st.exception(e)

if __name__ == "__main__":
    main()
