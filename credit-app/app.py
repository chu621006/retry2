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
        '抵免': 999.0, # Special value for '抵免' - treated as passed for credit count
        '通過': 999.0  # Special value for '通過' - treated as passed for credit count
    }
    return gpa_map.get(str(gpa_str).strip(), 0.0)

# --- 2. 成績分析函數 ---
def analyze_student_grades(df):
    """
    Analyzes a DataFrame of student grades to calculate total earned credits
    and remaining credits for graduation.
    """
    GRADUATION_REQUIREMENT = 128 # Set the total graduation requirement

    df['學分'] = pd.to_numeric(df['學分'], errors='coerce').fillna(0)
    df['GPA_Numeric'] = df['GPA'].apply(parse_gpa_to_numeric)
    
    # Define "passed" condition: GPA_Numeric >= 1.7 OR GPA is '抵免' OR GPA is '通過'
    # Use original 'GPA' column for '抵免'/'通過' check to avoid relying on 999.0 for actual GPA calculation
    # Also ensure 學分 is greater than 0 for credit counting
    df['是否通過'] = (df['GPA_Numeric'] >= 1.7) | \
                   (df['GPA'].astype(str).str.strip() == '抵免') | \
                   (df['GPA'].astype(str).str.strip() == '通過')
    
    # Filter for courses that passed and have credits > 0
    passed_courses_df = df[df['是否通過'] & (df['學分'] > 0)].copy()

    # Calculate total earned credits by summing '學分' for passed courses
    total_earned_credits = passed_courses_df['學分'].sum()
    
    # Calculate remaining credits: Graduation requirement minus total earned credits
    # Ensure it's not negative
    remaining_credits_to_graduate = max(0, GRADUATION_REQUIREMENT - total_earned_credits)

    return total_earned_credits, remaining_credits_to_graduate, passed_courses_df

# --- 3. 字元正規化函數 ---
def normalize_text(text):
    """
    Normalizes specific problematic Unicode characters often found in PDF extraction
    to their standard Traditional Chinese/ASCII counterparts.
    """
    if text is None:
        return ""
    text = str(text).replace('\n', ' ').strip()
    # Normalize common full-width or variant characters
    text = text.replace('⽬', '目') # CJK UNIFIED IDEOGRAPH-2F4D -> CJK UNIFIED IDEOGRAPH-76EE (目)
    text = text.replace('⽇', '日') # CJK UNIFIED IDEOGRAPH-2F31 -> CJK UNIFIED IDEOGRAPH-65E5 (日)
    text = text.replace('（', '(') # FULLWIDTH LEFT PARENTHESIS -> LEFT PARENTHESIS
    text = text.replace('）', ')') # FULLWIDTH RIGHT PARENTHESIS -> RIGHT PARENTHESIS
    text = text.replace('⼀', '一') # CJK RADICAL ONE -> CJK UNIFIED IDEOGRAPH-4E00 (一)
    text = text.replace('Ｃ', 'C') # FULLWIDTH LATIN CAPITAL LETTER C -> LATIN CAPITAL LETTER C
    text = text.replace('Ａ', 'A') # FULLWIDTH LATIN CAPITAL LETTER A -> LATIN CAPITAL LETTER A
    text = text.replace('Ｂ', 'B') # FULLWIDTH LATIN CAPITAL LETTER B -> LATIN CAPITAL LETTER B
    text = text.replace('Ｄ', 'D') # FULLWIDTH LATIN CAPITAL LETTER D -> LATIN CAPITAL LETTER D
    text = text.replace('Ｅ', 'E') # FULLWIDTH LATIN CAPITAL LETTER E -> LATIN CAPITAL LETTER E
    text = text.replace('Ｆ', 'F') # FULLWIDTH LATIN CAPITAL LETTER F -> LATIN CAPITAL LETTER F
    text = text.replace('Ｇ', 'G') # FULLWIDTH LATIN CAPITAL LETTER G -> LATIN CAPITAL LETTER G
    return text


# --- Streamlit 應用程式主體 ---
def main():
    st.title("總學分查詢系統 🎓")
    st.write("請上傳您的成績總表 PDF 檔案，系統將會為您查詢目前總學分與距離畢業所需的學分。")
    st.info("💡 確保您的成績單 PDF 是清晰的表格格式，以獲得最佳解析效果。")

    uploaded_file = st.file_uploader("上傳成績總表 PDF 檔案", type=["pdf"])

    if uploaded_file is not None:
        st.success("檔案上傳成功！正在分析中...")

        try:
            all_grades_data = []
            expected_columns_order = ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]
            
            st.subheader("除錯資訊 (開發者專用) 🕵️")
            debug_info_placeholder = st.empty()
            debug_messages = []

            with pdfplumber.open(io.BytesIO(uploaded_file.getvalue())) as pdf:
                total_pages = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages):
                    debug_messages.append(f"--- 正在處理頁面 {page_num + 1}/{total_pages} ---")

                    # 這裡可以根據實際情況調整裁剪範圍，以確保表頭和表格數據都被包含
                    top_y_crop = 60 
                    bottom_y_crop = page.height 

                    cropped_page = page.crop((0, top_y_crop, page.width, bottom_y_crop)) 
                    
                    table_settings = {
                        "horizontal_strategy": "lines",
                        "vertical_strategy": "lines",
                        "snap_tolerance": 1,             
                        "text_tolerance": 1,             
                        "join_tolerance": 1,             
                        "min_words_horizontal": 1, 
                        "min_words_vertical": 1 
                    }
                    debug_messages.append(f"  使用的 table_settings: {table_settings}")
                    
                    tables = cropped_page.extract_tables(table_settings)
                    
                    debug_messages.append(f"頁面 {page_num + 1} 提取到 {len(tables)} 個表格。")
                    
                    if not tables:
                        debug_messages.append(f"頁面 {page_num + 1} 未提取到任何表格。")
                        continue

                    for table_idx, table in enumerate(tables):
                        debug_messages.append(f"--- 處理頁面 {page_num + 1} 的表格 {table_idx + 1} ---")
                        debug_messages.append(f"  原始提取的表格 (前5行): {table[:5]}") 

                        if not table or len(table) < 1: # 至少有一行
                            debug_messages.append(f"  表格 {table_idx + 1} 無效 (行數不足或為空)。")
                            continue

                        # 過濾掉表格開頭的完全空行
                        filtered_table = [row for row in table if any(c.strip() for c in row)]
                        if not filtered_table:
                            debug_messages.append(f"  過濾空行後表格 {table_idx + 1} 為空，跳過。")
                            continue
                        
                        header_row_found = False
                        header = []
                        header_row_start_idx = -1 # 初始化為-1，表示數據從第0行開始

                        # 首先嘗試在過濾後的表格前5行尋找明確的表頭
                        potential_header_search_range = min(len(filtered_table), 5) 
                        for h_idx in range(potential_header_search_range):
                            h_row = filtered_table[h_idx]
                            cleaned_h_row_list = [normalize_text(col) for col in h_row]

                            is_potential_header = True
                            if len(cleaned_h_row_list) >= len(expected_columns_order):
                                for kw in ["學年度", "科目名稱", "學分", "GPA"]: 
                                    if not any(kw in cell for cell in cleaned_h_row_list):
                                        is_potential_header = False
                                        break
                            else:
                                is_potential_header = False 
                            
                            if is_potential_header:
                                header = [normalize_text(col) for col in h_row] 
                                header_row_found = True
                                header_row_start_idx = h_idx 
                                break 
                        
                        if not header_row_found:
                            debug_messages.append(f"  未能識別出明確的表頭。嘗試檢查是否為數據延續。")
                            # 如果沒有找到明確的表頭，檢查第一條非空行是否像數據行
                            if len(filtered_table[0]) >= len(expected_columns_order): # 確保行足夠長
                                first_data_candidate_row = [normalize_text(col) for col in filtered_table[0]]
                                # 檢查第一列是否為3位數字的學年度，且第三列（選課代號）非空
                                if first_data_candidate_row[0].isdigit() and \
                                   len(first_data_candidate_row[0]) == 3 and \
                                   first_data_candidate_row[2].strip() != '': # 假設選課代號在第3列（索引2）
                                    
                                    debug_messages.append(f"  第一行 '{first_data_candidate_row[0]}' 像學年度，判斷為數據延續。")
                                    header = expected_columns_order # 假設列順序與預期一致
                                    header_row_start_idx = -1 # 表示數據從 filtered_table[0] 開始
                                else:
                                    debug_messages.append(f"  第一行不符合數據行格式，跳過此表格。")
                                    continue
                            else:
                                debug_messages.append(f"  第一行太短不符合數據行格式，跳過此表格。")
                                continue


                        debug_messages.append(f"  最終表頭: {header}")

                        col_to_index = {} 
                        index_to_col = {} 

                        for i, h_ext in enumerate(header):
                            if "學年度" in h_ext: col_to_index["學年度"] = i; index_to_col[i] = "學年度"
                            elif "學期" in h_ext: col_to_index["學期"] = i; index_to_col[i] = "學期"
                            elif "選課代號" in h_ext: col_to_index["選課代號"] = i; index_to_col[i] = "選課代號"
                            elif "科目名稱" in h_ext: col_to_index["科目名稱"] = i; index_to_col[i] = "科目名稱"
                            elif "學分" in h_ext: col_to_index["學分"] = i; index_to_col[i] = "學分"
                            elif "GPA" in h_ext: col_to_index["GPA"] = i; index_to_col[i] = "GPA"
                        
                        critical_cols_found = all(col in col_to_index for col in ["學年度", "科目名稱", "學分", "GPA"])
                        debug_messages.append(f"  關鍵列索引映射狀態: {critical_cols_found}")
                        if not critical_cols_found: 
                            debug_messages.append("  缺少關鍵表頭，跳過此表格。")
                            continue

                        # 獲取關鍵列的索引
                        學年度_idx = col_to_index.get("學年度")
                        學期_idx = col_to_index.get("學期")
                        選課代號_idx = col_to_index.get("選課代號")
                        科目名稱_idx = col_to_index.get("科目名稱")
                        學分_idx = col_to_index.get("學分")
                        GPA_idx = col_to_index.get("GPA")

                        processed_rows = []
                        current_row_data_temp = None 
                        
                        # 確定從 filtered_table 的哪一行開始處理數據
                        if header_row_start_idx == -1: # 如果是隱式表頭，從第一行開始
                            data_rows_to_process = filtered_table[:]
                        else: # 如果找到了明確表頭，從表頭下一行開始
                            data_rows_to_process = filtered_table[header_row_start_idx + 1:]

                        for row_num_in_table, row in enumerate(data_rows_to_process): 
                            cleaned_row = [normalize_text(c) for c in row]
                            
                            # 確保行足夠長，避免索引越界
                            # 這裡使用 max(索引) + 1，確保能訪問所有需要的列
                            if len(cleaned_row) < max(學年度_idx, 學期_idx, 選課代號_idx, 科目名稱_idx, 學分_idx, GPA_idx) + 1:
                                debug_messages.append(f"    原始行太短，跳過: {cleaned_row}")
                                continue

                            debug_messages.append(f"    --- 處理原始數據行 (Data Rows) {row_num_in_table} ---")
                            debug_messages.append(f"    原始數據行內容: {row}") 
                            debug_messages.append(f"    清洗後數據行內容: {cleaned_row}") 

                            is_new_grade_row = False
                            學年度_val = cleaned_row[學年度_idx]
                            選課代號_val = cleaned_row[選課代號_idx]
                            科目名稱_val = cleaned_row[科目名稱_idx]

                            # 新行判斷：學年度必須是3位數字，選課代號不能為空
                            if 學年度_val.isdigit() and len(學年度_val) == 3 and 選課代號_val.strip() != '':
                                is_new_grade_row = True
                                debug_messages.append(f"      判斷: 滿足新的成績行條件 (學年度='{學年度_val}', 選課代號='{選課代號_val}')")
                            else:
                                debug_messages.append(f"      判斷: 不符合新行條件 (學年度='{學年度_val}', 選課代號='{選課代號_val}')。")

                            if is_new_grade_row:
                                if current_row_data_temp: 
                                    reordered_row = [""] * len(expected_columns_order)
                                    for col_name, idx_in_header in col_to_index.items():
                                        if col_name in expected_columns_order:
                                            target_idx = expected_columns_order.index(col_name)
                                            if idx_in_header < len(current_row_data_temp): # 確保索引不越界
                                                reordered_row[target_idx] = current_row_data_temp[idx_in_header]
                                    processed_rows.append(reordered_row)
                                    debug_messages.append(f"      -> 前一行完成，重新排序並添加到 processed_rows: {processed_rows[-1]}")
                                
                                current_row_data_temp = list(cleaned_row) 
                                debug_messages.append(f"      -> 新的成績行開始累積: {current_row_data_temp}")
                            elif current_row_data_temp: 
                                debug_messages.append(f"      判斷: 檢查是否為當前行續行...")

                                # 假設續行時，學年度和選課代號都應該是空的
                                is_continuation_candidate = (學年度_val.strip() == '' and 選課代號_val.strip() == '')

                                is_subject_continuation = False
                                if is_continuation_candidate and 科目名稱_val.strip() != '':
                                    is_subject_continuation = True
                                    debug_messages.append(f"        -> 科目名稱續行：學年度/選課代號為空，科目名稱有內容。")
                                
                                is_gpa_continuation = False
                                GPA_val = cleaned_row[GPA_idx]
                                if is_continuation_candidate and GPA_val.strip() != '':
                                    is_gpa_continuation = True
                                    debug_messages.append(f"        -> GPA 續行：學年度/選課代號為空，GPA有內容。")
                                
                                is_completely_empty_row = not any(c.strip() for c in cleaned_row)
                                if is_completely_empty_row:
                                    debug_messages.append(f"        -> 檢測到完全空白行。")

                                if is_subject_continuation:
                                    current_row_data_temp[科目名稱_idx] += " " + 科目名稱_val
                                    debug_messages.append(f"      -> 科目名稱續行合併後: {current_row_data_temp}")
                                elif is_gpa_continuation:
                                    current_row_data_temp[GPA_idx] += " " + GPA_val
                                    debug_messages.append(f"      -> GPA 續行合併後: {current_row_data_temp}")
                                elif is_completely_empty_row:
                                    # 如果遇到完全空白行，認為前一條記錄結束
                                    if current_row_data_temp: 
                                        reordered_row = [""] * len(expected_columns_order)
                                        for col_name, idx_in_header in col_to_index.items():
                                            if col_name in expected_columns_order:
                                                target_idx = expected_columns_order.index(col_name)
                                                if idx_in_header < len(current_row_data_temp):
                                                    reordered_row[target_idx] = current_row_data_temp[idx_in_header]
                                        processed_rows.append(reordered_row)
                                        debug_messages.append(f"      -> 檢測到空白行，前一行完成並添加到 processed_rows: {processed_rows[-1]}")
                                    current_row_data_temp = None 
                                else: 
                                    # 如果不是新行，也不是明確的續行，也不是空白行，則當前累積的行結束
                                    debug_messages.append(f"      -> 不符合任何模式 (新行/續行/空白行)，視為雜訊或錯誤，結束當前行。")
                                    if current_row_data_temp: 
                                        reordered_row = [""] * len(expected_columns_order)
                                        for col_name, idx_in_header in col_to_index.items():
                                            if col_name in expected_columns_order:
                                                target_idx = expected_columns_order.index(col_name)
                                                if idx_in_header < len(current_row_data_temp):
                                                    reordered_row[target_idx] = current_row_data_temp[idx_in_header]
                                        processed_rows.append(reordered_row)
                                        debug_messages.append(f"      -> 將當前行添加到 processed_rows: {processed_rows[-1]}")
                                    current_row_data_temp = None 
                            else: 
                                debug_messages.append(f"      -> current_row_data_temp 為空，且當前行不符合新行條件，跳過。")
                                pass 

                        # 處理表格的最後一行
                        if current_row_data_temp: 
                            reordered_row = [""] * len(expected_columns_order)
                            for col_name, idx_in_header in col_to_index.items():
                                if col_name in expected_columns_order:
                                    target_idx = expected_columns_order.index(col_name)
                                    if idx_in_header < len(current_row_data_temp):
                                        reordered_row[target_idx] = current_row_data_temp[idx_in_header]
                            processed_rows.append(reordered_row)
                            debug_messages.append(f"  最後一行完成，重新排序並添加到 processed_rows: {processed_rows[-1]}")

                        debug_messages.append(f"  處理後有效行數: {len(processed_rows)}")
                        debug_messages.append(f"  處理後部分數據 (前5行): {processed_rows[:5]}")

                        if processed_rows:
                            df_table = pd.DataFrame(processed_rows, columns=expected_columns_order)
                            
                            for col in df_table.columns:
                                df_table[col] = df_table[col].astype(str).str.strip().replace('None', '').replace('nan', '')

                            all_grades_data.append(df_table)
                        else:
                            debug_messages.append(f"  此表格未能提取到任何有效數據行。")

                    debug_info_placeholder.text("\n".join(debug_messages)) 

            if not all_grades_data:
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式或調整表格提取設定。")
                full_grades_df = pd.DataFrame(columns=expected_columns_order)
                return

            full_grades_df = pd.concat(all_grades_data, ignore_index=True)

            # 再次清理整個DataFrame，確保沒有完全空行，並且根據學年度篩選
            full_grades_df.dropna(how='all', inplace=True)
            
            # 使用更嚴格的學年度篩選，確保是三位數字
            initial_rows = len(full_grades_df)
            full_grades_df = full_grades_df[
                full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$')
            ]
            debug_messages.append(f"原始數據行數: {initial_rows}, 經過學年度篩選後: {len(full_grades_df)}")

            # 過濾勞作成績，確保科目名稱列存在
            if '科目名稱' in full_grades_df.columns:
                full_grades_df = full_grades_df[~full_grades_df['科目名稱'].astype(str).str.contains('勞作成績', na=False)]
                debug_messages.append(f"過濾勞作成績後行數: {len(full_grades_df)}")
            
            # 確保 GPA 列是字串類型並清理空白
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
        finally: 
            debug_info_placeholder.text("\n".join(debug_messages))

if __name__ == "__main__":
    main()
