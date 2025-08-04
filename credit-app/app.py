import streamlit as st
import pandas as pd
import io
import pdfplumber # 改用 pdfplumber，它不需要 Java

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
        '抵免': 999.0, # Assign a very high value for '抵免' to ensure it passes
        '通過': 999.0  # Assign a very high value for '通過' to ensure it passes
    }
    # 處理可能存在的空白字元
    return gpa_map.get(gpa_str.strip(), 0.0)

# --- 2. 成績分析函數 ---
def analyze_student_grades(df):
    """
    Analyzes a DataFrame of student grades to calculate total earned credits
    and remaining credits for graduation.

    Args:
        df (pd.DataFrame): DataFrame containing '學分' (credits) and 'GPA' columns.

    Returns:
        tuple: (total_earned_credits, remaining_credits_to_graduate, passed_courses_df)
    """
    GRADUATION_REQUIREMENT = 128

    # 確保 '學分' 是數值，並將錯誤轉換為 NaN，然後填充為 0
    df['學分'] = pd.to_numeric(df['學分'], errors='coerce').fillna(0)

    # 將 GPA 轉換為數值表示進行比較
    df['GPA_Numeric'] = df['GPA'].apply(parse_gpa_to_numeric)

    # 判斷課程是否通過 (C- 等價或更高，或 '抵免'，或 '通過')
    # C- 對應到我們的映射中的數值 1.7
    df['是否通過'] = df['GPA_Numeric'].apply(lambda x: x >= 1.7)

    # 過濾出通過的課程，並且學分大於 0 (排除體育、軍訓等 0 學分的課程，除非它們明確算入畢業學分)
    # 也排除可能存在的總結行，如「勞作成績為:未通過」
    passed_courses_df = df[df['是否通過'] & (df['學分'] > 0)].copy()

    # 計算總獲得學分
    total_earned_credits = passed_courses_df['學分'].sum()

    # 計算距離畢業還差的學分
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
            # 使用 pdfplumber 讀取 PDF
            with pdfplumber.open(io.BytesIO(uploaded_file.getvalue())) as pdf:
                all_grades_data = []
                for page in pdf.pages:
                    # 嘗試從每個頁面提取表格
                    # settings 可以根據您的 PDF 調整，例如 vertical_strategy, horizontal_strategy
                    # 這裡使用預設的 setting
                    tables = page.extract_tables()

                    for table in tables:
                        # 每個 table 是一個列表的列表 (list of lists)，代表表格的行和列
                        # 我們需要找到包含成績數據的表格
                        # 根據您的 PDF 範例，表格的第一行通常是標題，例如「學年度」
                        if table and len(table[0]) >= 6 and '學年度' in table[0][0]:
                            # 將表格轉換為 Pandas DataFrame
                            df_table = pd.DataFrame(table[1:], columns=table[0]) # 跳過標題行
                            all_grades_data.append(df_table)

            if not all_grades_data:
                st.warning("未能從 PDF 中提取任何表格。請檢查 PDF 格式或嘗試調整解析參數。")
                return

            # 合併所有提取到的 DataFrame
            full_grades_df = pd.concat(all_grades_data, ignore_index=True)

            # 數據清洗
            # 移除所有列都是 NaN 的行 (可能來自解析錯誤)
            full_grades_df.dropna(how='all', inplace=True)
            # 移除可能由於 PDF 解析造成的空白字元和換行符
            for col in full_grades_df.columns:
                if col in ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]: # 僅清理相關列
                    full_grades_df[col] = full_grades_df[col].astype(str).str.strip().str.replace('\n', ' ', regex=False)
            
            # 過濾掉那些明顯不是成績行的資料，例如開頭不是數字的學年度，或者勞作成績那一行
            full_grades_df = full_grades_df[
                full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$') &
                ~full_grades_df['科目名稱'].astype(str).str.contains('勞作成績', na=False)
            ]
            
            # 確保 GPA 列是字串類型以進行 .strip() 操作
            full_grades_df['GPA'] = full_grades_df['GPA'].astype(str).str.strip()

            if not full_grades_df.empty:
                # 執行學分分析
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
            st.exception(e) # 顯示更詳細的錯誤信息

if __name__ == "__main__":
    main()