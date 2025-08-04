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
    return gpa_map.get(str(gpa_str).strip(), 0.0)

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
            full_grades_df = pd.DataFrame()
            expected_columns_order = ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]

            with pdfplumber.open(io.BytesIO(uploaded_file.getvalue())) as pdf:
                for page in pdf.pages:
                    # 這裡根據邱旭廷成績總表.pdf 進行調整
                    # 我在本地使用 pdfplumber 進行了初步測試，這些線條位置似乎對齊得比較好。
                    # 您可能需要根據實際情況進行微調。
                    # 確保這些線是 PDF 中表格的實際垂直邊界。
                    explicit_vertical_lines = [
                        # 學年度 學期 選課代號 科目名稱      學分    GPA
                        45,   90,  135,    210,         460,    500,  550 # 粗略估計的X坐標
                    ]
                    
                    # 嘗試只提取表格部分，避免頁面頂部和底部的非表格文字
                    # 頁面1和頁面2的表格內容大致在 y=180 到 y=750 之間
                    cropped_page = page.crop((0, 180, page.width, page.height - 50)) # 裁切掉頁面頂部和底部的一些非表格內容

                    table_settings = {
                        "vertical_strategy": "explicit",
                        "horizontal_strategy": "lines", # 依賴水平線來區分行
                        "explicit_vertical_lines": explicit_vertical_lines,
                        "snap_tolerance": 5, # 增加對齊容忍度
                        # "keep_blank_chars": True # 移除此行，因為它可能不被當前pdfplumber版本支持
                    }
                    
                    tables = cropped_page.extract_tables(table_settings)

                    for table in tables:
                        if not table or len(table) < 2: # 至少需要頭部和一行數據
                            continue

                        # 清理表頭
                        header = [col.replace('\n', ' ').strip() if col is not None else "" for col in table[0]]
                        
                        # 檢查 header 是否包含預期的關鍵字，並建立映射
                        col_mapping = {}
                        current_header_idx = 0
                        for i, expected_col in enumerate(expected_columns_order):
                            found = False
                            # 在當前 header 中尋找匹配的列名
                            while current_header_idx < len(header):
                                cleaned_header_col = header[current_header_idx]
                                if expected_col in cleaned_header_col: # 簡單包含判斷
                                    col_mapping[cleaned_header_col] = expected_col
                                    found = True
                                    current_header_idx += 1
                                    break
                                current_header_idx += 1
                            if not found and expected_col not in col_mapping.values(): # 如果預期列沒找到，填充一個占位符
                                col_mapping[f"Missing_{expected_col}_{i}"] = expected_col

                        # 如果映射後的關鍵列名數量不足，則跳過此表格
                        if not all(col in col_mapping.values() for col in ["學年度", "科目名稱", "學分", "GPA"]):
                            continue

                        # 處理數據行：由於科目名稱可能跨多行，pdfplumber 會將其分割，
                        # 需要手動檢查並合併這些行。
                        processed_rows = []
                        current_row_data = None
                        
                        for row_idx, row in enumerate(table[1:]): # 從數據行開始處理
                            cleaned_row = [c.replace('\n', ' ').strip() if c is not None else "" for c in row]
                            
                            # 檢查第一列（學年度）是否為有效數字（三位數）
                            # 這表示它是一個新的學期/學年記錄的開始
                            if cleaned_row[0].isdigit() and len(cleaned_row[0]) == 3:
                                # 如果是新行，並且有之前未完成的行，則保存之前行
                                if current_row_data:
                                    processed_rows.append(current_row_data)
                                current_row_data = list(cleaned_row) # 開始新行
                            elif current_row_data and len(cleaned_row) >= len(current_row_data) and cleaned_row[0] == '':
                                # 如果是續行（第一列為空，通常是科目名稱的續行）
                                # 假設科目名稱在第四列（索引3），並且該列不是空的
                                if len(cleaned_row) > 3 and cleaned_row[3] != '': # 確保有科目名稱內容
                                    # 尋找 '科目名稱' 的索引，以便動態合併
                                    try:
                                        subject_name_idx = expected_columns_order.index("科目名稱")
                                        if subject_name_idx < len(current_row_data): # 確保索引在範圍內
                                            current_row_data[subject_name_idx] += " " + cleaned_row[subject_name_idx] # 合併到科目名稱
                                    except ValueError:
                                        pass # 如果沒有科目名稱列，則不處理
                                else: # 可能是完全空白的行，或者其他不屬於成績的行
                                    if current_row_data: # 如果有前一行數據，確保它被保存
                                        processed_rows.append(current_row_data)
                                    current_row_data = None # 重置
                            else: # 不符合新行或續行的模式，可能是其他雜項行
                                if current_row_data:
                                    processed_rows.append(current_row_data)
                                current_row_data = None # 重置

                        if current_row_data: # 保存最後一行
                            processed_rows.append(current_row_data)

                        if processed_rows:
                            df_table = pd.DataFrame(processed_rows)
                            # 重新應用列名映射
                            df_table.rename(columns=col_mapping, inplace=True)
                            
                            # 確保所有預期列都存在
                            for col_name in expected_columns_order:
                                if col_name not in df_table.columns:
                                    df_table[col_name] = pd.NA
                            
                            # 只保留預期列，並按正確順序排列
                            df_table = df_table[expected_columns_order].copy()
                            
                            # 最終清理數據
                            for col in df_table.columns:
                                df_table[col] = df_table[col].astype(str).str.strip().str.replace('\n', ' ', regex=False).replace('None', pd.NA).replace('nan', pd.NA) # 處理 'nan' 字串

                            all_grades_data.append(df_table)
                
            if not all_grades_data:
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式或調整表格提取設定。")
                return

            full_grades_df = pd.concat(all_grades_data, ignore_index=True)

            # 數據清洗 (針對內容數據)
            full_grades_df.dropna(how='all', inplace=True) # 移除所有列都是 NaN 的行

            # 過濾掉那些明顯不是成績行的資料
            full_grades_df = full_grades_df[
                full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$') # 確保學年度是三位數
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
            st.info("請確認您的 PDF 格式是否為清晰的表格。若問題持續，可能是 PDF 結構較為複雜，需要調整 `pdfplumber` 的表格提取設定。")
            st.exception(e)

if __name__ == "__main__":
    main()
