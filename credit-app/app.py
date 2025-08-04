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
            all_grades_data = [] # 確保在 try 區塊開始時定義
            expected_columns_order = ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]

            with pdfplumber.open(io.BytesIO(uploaded_file.getvalue())) as pdf:
                for page_num, page in enumerate(pdf.pages): # 加入 page_num 以便除錯
                    # 這些是基於「邱旭廷成績總表.pdf」的觀察值，可能需要微調
                    # 建議在本地使用 pdfplumber 的 debug 模式來視覺化這些線條
                    explicit_vertical_lines = [
                        45,   90,  135,    210,         460,    500,  550 # 粗略估計的X坐標
                    ]
                    
                    # 裁切頁面以專注於表格區域，避免頁面頂部和底部的非表格文字
                    # 對於成績總表，表格內容大致從 Y=180 左右開始
                    # page.height - 50 是為了避免裁切到頁腳資訊，如果表格延伸到頁底，可能需要調整為 page.height
                    cropped_page = page.crop((0, 180, page.width, page.height - 50)) 

                    table_settings = {
                        "vertical_strategy": "explicit", # 明確指定垂直線
                        "horizontal_strategy": "lines", # 依賴水平線來區分行
                        "explicit_vertical_lines": explicit_vertical_lines,
                        "snap_tolerance": 5, # 增加對齊容忍度
                    }
                    
                    tables = cropped_page.extract_tables(table_settings)

                    for table_idx, table in enumerate(tables):
                        if not table or len(table) < 2: # 至少需要頭部和一行數據
                            continue

                        # 清理表頭，並處理 None 值
                        header = [col.replace('\n', ' ').strip() if col is not None else "" for col in table[0]]
                        
                        # 建立一個映射，從提取到的列名到標準列名，並記錄索引
                        # 這使得程式碼對列順序和名稱變化更健壯
                        col_to_index = {} # 存放標準列名 -> 提取表格中的索引
                        index_to_col = {} # 存放提取表格中的索引 -> 標準列名

                        for i, h_ext in enumerate(header):
                            if "學年度" in h_ext: col_to_index["學年度"] = i; index_to_col[i] = "學年度"
                            elif "學期" in h_ext: col_to_index["學期"] = i; index_to_col[i] = "學期"
                            elif "選課代號" in h_ext: col_to_index["選課代號"] = i; index_to_col[i] = "選課代號"
                            elif "科目名稱" in h_ext: col_to_index["科目名稱"] = i; index_to_col[i] = "科目名稱"
                            elif "學分" in h_ext: col_to_index["學分"] = i; index_to_col[i] = "學分"
                            elif "GPA" in h_ext: col_to_index["GPA"] = i; index_to_col[i] = "GPA"
                            # 對於其他未識別的列，如果需要，可以給它們一個臨時名稱
                            # else: index_to_col[i] = f"Unknown_Col_{i}"

                        # 檢查所有關鍵列是否都被識別
                        critical_cols_found = all(col in col_to_index for col in ["學年度", "科目名稱", "學分", "GPA"])
                        if not critical_cols_found:
                            continue # 如果關鍵列缺失，跳過此表格

                        # 動態獲取關鍵列的索引
                        學年度_idx = col_to_index.get("學年度")
                        科目名稱_idx = col_to_index.get("科目名稱")
                        學分_idx = col_to_index.get("學分")
                        GPA_idx = col_to_index.get("GPA")

                        processed_rows = []
                        current_row_data = None # 用於組合跨行數據

                        for row in table[1:]: # 從數據行開始
                            # 清理當前行的所有單元格
                            cleaned_row = [c.replace('\n', ' ').strip() if c is not None else "" for c in row]
                            
                            # 判斷是否為新的一行成績記錄：檢查「學年度」列是否有三位數字
                            if 學年度_idx is not None and cleaned_row[學年度_idx].isdigit() and len(cleaned_row[學年度_idx]) == 3:
                                if current_row_data:
                                    # 如果有之前未完成的行，先將其保存
                                    processed_rows.append(current_row_data)
                                # 開始新的行數據
                                current_row_data = cleaned_row
                            elif current_row_data and 學年度_idx is not None and cleaned_row[學年度_idx] == '':
                                # 判斷是否為「科目名稱」的續行 (學年度為空，且科目名稱有內容)
                                if 科目名稱_idx is not None and cleaned_row[科目名稱_idx] != '':
                                    # 將當前行的科目名稱內容合併到前一行
                                    current_row_data[科目名稱_idx] += " " + cleaned_row[科目名稱_idx]
                                    # 注意：這裡假設只有科目名稱會跨行，如果其他列也會跨行，則需要更複雜的合併邏輯
                                else:
                                    # 如果是空行或其他不符合模式的行，則結束前一行並開始新的處理 (這裡我們直接忽略)
                                    # 這防止了空行被錯誤地合併
                                    if current_row_data:
                                        processed_rows.append(current_row_data)
                                    current_row_data = None
                            else: # 不符合新行或續行的模式，可能是表格外的文字或雜項，直接忽略
                                if current_row_data: # 如果有數據正在處理，則結束並保存
                                    processed_rows.append(current_row_data)
                                current_row_data = None


                        if current_row_data: # 添加最後處理完的行
                            processed_rows.append(current_row_data)

                        if processed_rows:
                            # 使用處理後的行數據創建 DataFrame
                            df_table = pd.DataFrame(processed_rows)
                            
                            # 使用 index_to_col 字典進行列重命名，確保正確的標準列名
                            df_table.rename(columns=index_to_col, inplace=True)
                            
                            # 確保所有預期列都存在，如果缺失則添加並填充 NaN
                            for col_name in expected_columns_order:
                                if col_name not in df_table.columns:
                                    df_table[col_name] = pd.NA
                            
                            # 只保留預期列，並按正確順序排列
                            df_table = df_table[expected_columns_order].copy() # 使用 .copy() 避免 SettingWithCopyWarning
                            
                            # 最終清理數據行中的 'None' 和 'nan' 字串
                            for col in df_table.columns:
                                df_table[col] = df_table[col].astype(str).str.strip().str.replace('None', '').replace('nan', '')

                            all_grades_data.append(df_table)
                
            if not all_grades_data:
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式或調整表格提取設定。")
                # 如果沒有提取到任何數據，初始化一個空的 DataFrame，避免後續錯誤
                full_grades_df = pd.DataFrame(columns=expected_columns_order)
                return

            full_grades_df = pd.concat(all_grades_data, ignore_index=True)

            # 數據清洗 (針對內容數據)
            full_grades_df.dropna(how='all', inplace=True) # 移除所有列都是 NaN 的行

            # 過濾掉那些明顯不是成績行的資料
            # 確保 '學年度' 是三位數的數字
            full_grades_df = full_grades_df[
                full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$')
            ]
            
            # 過濾掉勞作成績
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
