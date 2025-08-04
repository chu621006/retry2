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
    # Ensure gpa_str is treated as string, then strip, then get from map
    return gpa_map.get(str(gpa_str).strip(), 0.0)

# --- 2. 成績分析函數 ---
def analyze_student_grades(df):
    """
    Analyzes a DataFrame of student grades to calculate total earned credits
    and remaining credits for graduation.
    """
    GRADUATION_REQUIREMENT = 128 # Set the total graduation requirement

    df['學分'] = pd.to_numeric(df['學分'], errors='coerce').fillna(0)
    
    # Ensure GPA column is string before applying parse_gpa_to_numeric
    df['GPA_Numeric'] = df['GPA'].astype(str).apply(parse_gpa_to_numeric)
    
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
    to their standard Traditional Chinese/ASCII counterparts. Handles None input.
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
    text = text.text.replace('Ｄ', 'D') # FULLWIDTH LATIN CAPITAL LETTER D -> LATIN CAPITAL LETTER D
    text = text.replace('Ｅ', 'E') # FULLWIDTH LATIN CAPITAL LETTER E -> LATIN CAPITAL LETTER E
    text = text.replace('Ｆ', 'F') # FULLWIDTH LATIN CAPITAL LETTER F -> LATIN CAPITAL LETTER F
    text = text.replace('Ｇ', 'G') # FULLWIDTH LATIN CAPITAL LETTER G -> LATIN CAPITAL LETTER G
    return text.strip() # 再次strip以防替換後產生前後空格

# --- 4. 處理分行GPA/學分問題的函數 (在提取原始表格後立即應用) ---
def parse_gpa_credit_from_combined_cell(gpa_cell_content, credit_cell_content):
    """
    Handles cases where GPA and credit are combined in one cell, or extracted incorrectly.
    Returns cleaned GPA and credit values.
    """
    gpa = str(gpa_cell_content).strip()
    credit = str(credit_cell_content).strip()

    # Case 1: GPA cell contains both GPA and credit separated by newline
    if '\n' in gpa and credit == '':
        parts = gpa.split('\n')
        if len(parts) == 2:
            # The order might be GPA \n Credit or Credit \n GPA.
            # We need to determine which is which.
            gpa_candidate = parts[0].strip()
            credit_candidate = parts[1].strip()

            # If credit_candidate looks like a number, and gpa_candidate looks like a GPA grade
            if credit_candidate.replace('.', '').isdigit() and (gpa_candidate.isalpha() or gpa_candidate in ['抵免', '通過']):
                return gpa_candidate, credit_candidate
            elif gpa_candidate.replace('.', '').isdigit() and (credit_candidate.isalpha() or credit_candidate in ['抵免', '通過']):
                # If it's reversed (Credit \n GPA)
                return credit_candidate, gpa_candidate
            
    # Case 2: Credit cell contains both GPA and credit separated by newline
    if '\n' in credit and gpa == '':
        parts = credit.split('\n')
        if len(parts) == 2:
            credit_candidate = parts[0].strip()
            gpa_candidate = parts[1].strip()
            if credit_candidate.replace('.', '').isdigit() and (gpa_candidate.isalpha() or gpa_candidate in ['抵免', '通過']):
                return gpa_candidate, credit_candidate
            elif gpa_candidate.replace('.', '').isdigit() and (credit_candidate.isalpha() or credit_candidate in ['抵免', '通過']):
                 # If it's reversed (GPA \n Credit)
                return credit_candidate, gpa_candidate
    
    # Return original values if no specific pattern is matched
    return gpa, credit

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
            # 確保欄位名稱與 PDF 中實際提取出的名稱一致
            # 這些是您 PDF 中表頭可能出現的詞，用於判斷列
            expected_header_keywords = ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]
            
            with pdfplumber.open(io.BytesIO(uploaded_file.getvalue())) as pdf:
                total_pages = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages):
                    # 根據經驗，前幾行可能是標題或無關信息，可以裁剪掉
                    # 謝云瑄成績總表.pdf 的第一頁約 70 pixel 以下是表格開始
                    # 其他頁面可能不需要這麼高的裁剪
                    # 邱旭廷的PDF第一頁表格位置較低，但第二頁開始就比較固定
                    top_y_crop = 170 if page_num == 0 else 50 # 針對第一頁做更多裁剪
                    bottom_y_crop = page.height - 30 # 保留底部30像素用於頁碼/網址，避免影響表格

                    cropped_page = page.crop((0, top_y_crop, page.width, bottom_y_crop)) 
                    
                    # 針對 pdfplumber 0.7.0 版本調整 table_settings
                    # 0.7.0 版本沒有 horizontal_strategy 和 vertical_strategy
                    # 而是使用 table_settings 來控制表格提取
                    table_settings = {
                        "vertical_strategy": "lines", # 嘗試用 lines 策略，若不行可改為 "text"
                        "horizontal_strategy": "lines", # 嘗試用 lines 策略，若不行可改為 "text"
                        "snap_tolerance": 3, # 增加容錯度，允許線條有小偏差
                        "text_tolerance": 3, # 增加文字容錯度
                        "join_tolerance": 3, # 增加合併容錯度
                        "edge_min_length": 3, # 最小邊長，避免提取到雜訊
                        "min_words_horizontal": 1, # 一行最少一個詞
                        "min_words_vertical": 1 # 一列最少一個詞
                    }
                    
                    tables = cropped_page.extract_tables(table_settings)
                    
                    if not tables:
                        continue # 如果當前頁面沒有提取到表格，直接跳過

                    for table_idx, table in enumerate(tables):
                        if not table or len(table) < 1: 
                            continue

                        # 對每個單元格先轉字串再 strip，並過濾掉完全空行
                        # 在這裡應用 normalize_text
                        filtered_table = [
                            [normalize_text(cell) for cell in row]
                            for row in table if any(normalize_text(cell).strip() for cell in row)
                        ]
                        if not filtered_table:
                            continue
                        
                        header_row_found = False
                        header = []
                        header_row_start_idx = -1 # 初始化為-1，表示數據從第0行開始

                        # 尋找表頭：檢查前幾行是否包含關鍵字
                        # 檢查前5行，因為表頭可能佔多行
                        potential_header_search_range = min(len(filtered_table), 5)
                        for h_idx in range(potential_header_search_range):
                            h_row_cells = [cell for cell in filtered_table[h_idx]] # 已經過 normalize_text
                            
                            # 檢查是否有足夠的關鍵字來識別為表頭
                            # 至少包含 "學年度", "科目名稱", "學分", "GPA"
                            # 由於表頭可能多行顯示，這裡只需要判斷是否存在關鍵字，不要求完全匹配單一列名
                            # 這裡更寬鬆一些，只要包含主要幾個就認為是表頭
                            if all(any(kw in cell for cell in h_row_cells) for kw in ["學年度", "科目名稱", "學分", "GPA"]):
                                header = h_row_cells
                                header_row_found = True
                                header_row_start_idx = h_idx
                                break
                        
                        # 如果沒有找到明確的表頭，嘗試將預期列作為表頭，並假設數據從第一行開始
                        if not header_row_found:
                            # 檢查第一行數據是否像成績數據（學年度是3位數字）
                            if len(filtered_table[0]) > 0 and filtered_table[0][0].isdigit() and len(filtered_table[0][0]) == 3:
                                header = expected_header_keywords # 假設列順序與預期一致
                                header_row_start_idx = -1 # 表示數據從 filtered_table[0] 開始
                                header_row_found = True # 標記為找到表頭 (默認表頭)
                            else:
                                continue # 如果不像數據行，則跳過此表格

                        # 動態映射列名到索引
                        col_to_index = {}
                        # 嘗試根據關鍵字查找列的索引，優先匹配完整名稱
                        # 處理表頭單字換行問題，例如 "學\n年\n度"
                        for i, h_text in enumerate(header):
                            if "學年度" in h_text.replace(' ', ''): col_to_index["學年度"] = i
                            elif "學期" in h_text.replace(' ', ''): col_to_index["學期"] = i
                            elif "選課代號" in h_text.replace(' ', ''): col_to_index["選課代號"] = i
                            elif "科目名稱" in h_text.replace(' ', ''): col_to_index["科目名稱"] = i
                            elif "學分" in h_text.replace(' ', ''): col_to_index["學分"] = i
                            elif "GPA" in h_text.replace(' ', ''): col_to_index["GPA"] = i

                        # 檢查是否找到所有關鍵列
                        critical_cols = ["學年度", "科目名稱", "學分", "GPA"]
                        if not all(col in col_to_index for col in critical_cols):
                            # 如果缺少關鍵列，則跳過此表格 (或打印警告)
                            # st.warning(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 缺少關鍵列，跳過。")
                            continue

                        # 獲取關鍵列的索引 (使用 .get() 確保安全，如果沒有找到則為 None)
                        學年度_idx = col_to_index.get("學年度")
                        學期_idx = col_to_index.get("學期")
                        選課代號_idx = col_to_index.get("選課代號")
                        科目名稱_idx = col_to_index.get("科目名稱")
                        學分_idx = col_to_index.get("學分")
                        GPA_idx = col_to_index.get("GPA")

                        # 構建新的數據行
                        processed_rows = []
                        # current_row_data_temp 儲存當前正在處理的行數據，用於合併跨行內容
                        current_row_data_temp = [None] * len(expected_header_keywords) 

                        # 確定從 filtered_table 的哪一行開始處理數據
                        data_rows_to_process = filtered_table[header_row_start_idx + 1:] if header_row_start_idx != -1 else filtered_table[:]

                        for row_num_in_table, row_cells in enumerate(data_rows_to_process):
                            # 過濾掉只包含空字串或 None 的行
                            if not any(cell.strip() for cell in row_cells):
                                continue

                            # 確保行足夠長，避免索引越界
                            max_idx_needed = -1
                            for idx in [學年度_idx, 學期_idx, 選課代號_idx, 科目名稱_idx, 學分_idx, GPA_idx]:
                                if idx is not None:
                                    max_idx_needed = max(max_idx_needed, idx)
                            
                            # 獲取關鍵列的值
                            學年度_val = row_cells[學年度_idx] if 學年度_idx is not None and 學年度_idx < len(row_cells) else ''
                            選課代號_val = row_cells[選課代號_idx] if 選課代號_idx is not None and 選課代號_idx < len(row_cells) else ''
                            科目名稱_val = row_cells[科目名稱_idx] if 科目名稱_idx is not None and 科目名稱_idx < len(row_cells) else ''
                            學分_val = row_cells[學分_idx] if 學分_idx is not None and 學分_idx < len(row_cells) else ''
                            GPA_val = row_cells[GPA_idx] if GPA_idx is not None and GPA_idx < len(row_cells) else ''

                            # 判斷是否為新成績行
                            # 新行的標誌：學年度是3位數字 AND 選課代號或科目名稱不為空
                            is_new_grade_row = False
                            if 學年度_val.isdigit() and len(學年度_val) == 3 and \
                               (選課代號_val.strip() != '' or 科目名稱_val.strip() != ''):
                                is_new_grade_row = True
                            
                            if is_new_grade_row:
                                # 如果是新成績行，則將上一行的累積數據添加到 processed_rows
                                if current_row_data_temp and any(x is not None and x.strip() for x in current_row_data_temp):
                                    processed_rows.append(current_row_data_temp[:]) # 添加副本
                                
                                # 初始化新的 current_row_data_temp
                                current_row_data_temp = [""] * len(expected_header_keywords) # 初始化為空字串

                                # 填充新行的數據
                                if 學年度_idx is not None: current_row_data_temp[expected_header_keywords.index("學年度")] = 學年度_val
                                if 學期_idx is not None: current_row_data_temp[expected_header_keywords.index("學期")] = (row_cells[學期_idx] if 學期_idx < len(row_cells) else '')
                                if 選課代號_idx is not None: current_row_data_temp[expected_header_keywords.index("選課代號")] = 選課代號_val
                                if 科目名稱_idx is not None: current_row_data_temp[expected_header_keywords.index("科目名稱")] = 科目名稱_val
                                if 學分_idx is not None: current_row_data_temp[expected_header_keywords.index("學分")] = 學分_val
                                if GPA_idx is not None: current_row_data_temp[expected_header_keywords.index("GPA")] = GPA_val
                                
                                # 在這裡處理單元格內 GPA/學分混寫的情況
                                current_gpa, current_credit = parse_gpa_credit_from_combined_cell(
                                    current_row_data_temp[expected_header_keywords.index("GPA")],
                                    current_row_data_temp[expected_header_keywords.index("學分")]
                                )
                                current_row_data_temp[expected_header_keywords.index("GPA")] = current_gpa
                                current_row_data_temp[expected_header_keywords.index("學分")] = current_credit

                            elif current_row_data_temp: 
                                # 處理跨行數據（科目名稱或GPA/學分可能換行）
                                # 判斷是否為續行：學年度和選課代號都應該是空的
                                is_continuation_candidate = (學年度_val.strip() == '' and 選課代號_val.strip() == '')

                                # 合併科目名稱
                                if is_continuation_candidate and 科目名稱_val.strip() != '':
                                    if current_row_data_temp[expected_header_keywords.index("科目名稱")].strip() == "":
                                        current_row_data_temp[expected_header_keywords.index("科目名稱")] = 科目名稱_val
                                    else:
                                        current_row_data_temp[expected_header_keywords.index("科目名稱")] += " " + 科目名稱_val
                                
                                # 合併學分和GPA，並優先處理 `parse_gpa_credit_from_combined_cell`
                                # 如果當前行的 學分 和 GPA 欄位不為空，且 學年度 和 選課代號 為空，則嘗試合併
                                if is_continuation_candidate and (學分_val.strip() != '' or GPA_val.strip() != ''):
                                    merged_gpa, merged_credit = parse_gpa_credit_from_combined_cell(GPA_val, 學分_val)
                                    
                                    # 如果學分是數字，則更新，否則繼續累積
                                    if merged_credit.replace('.', '').isdigit() and float(merged_credit) > 0:
                                        current_row_data_temp[expected_header_keywords.index("學分")] = merged_credit
                                    elif current_row_data_temp[expected_header_keywords.index("學分")].strip() == "" and 學分_val.strip() != "":
                                        current_row_data_temp[expected_header_keywords.index("學分")] = 學分_val
                                    
                                    # 如果 GPA 像個成績等級，則更新
                                    if merged_gpa.strip() != '' and (merged_gpa.isalpha() or merged_gpa in ['抵免', '通過']):
                                        current_row_data_temp[expected_header_keywords.index("GPA")] = merged_gpa
                                    elif current_row_data_temp[expected_header_keywords.index("GPA")].strip() == "" and GPA_val.strip() != "":
                                        current_row_data_temp[expected_header_keywords.index("GPA")] = GPA_val


                        # 處理表格的最後一行
                        if current_row_data_temp and any(x is not None and x.strip() for x in current_row_data_temp): 
                            processed_rows.append(current_row_data_temp[:])
                        
                        if processed_rows:
                            # 確保DataFrame的列名是固定的 expected_header_keywords
                            df_table = pd.DataFrame(processed_rows, columns=expected_header_keywords)
                            
                            # 對整個DataFrame進行最後的清理，去除None、nan字串
                            for col in df_table.columns:
                                df_table[col] = df_table[col].astype(str).str.strip().replace('None', '').replace('nan', '')

                            all_grades_data.append(df_table)
                        else:
                            pass # 沒有提取到有效數據的表格就跳過

            if not all_grades_data:
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式或調整表格提取設定。")
                # 即使沒有數據，也創建一個空的 DataFrame 以免後續報錯
                full_grades_df = pd.DataFrame(columns=expected_header_keywords)
                return

            full_grades_df = pd.concat(all_grades_data, ignore_index=True)

            # 再次清理整個DataFrame，確保沒有完全空行，並且根據學年度篩選
            full_grades_df.dropna(how='all', inplace=True)
            
            # 使用更嚴格的學年度篩選，確保是三位數字
            # 並清理選課代號中的None或空字串
            full_grades_df = full_grades_df[
                full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$') &
                (full_grades_df['選課代號'].astype(str).str.strip() != '') # 確保選課代號不為空
            ]

            # 過濾勞作成績，確保科目名稱列存在
            if '科目名稱' in full_grades_df.columns:
                full_grades_df = full_grades_df[~full_grades_df['科目名稱'].astype(str).str.contains('勞作成績', na=False)]
            
            # 確保 GPA 列是字串類型並清理空白
            full_grades_df['GPA'] = full_grades_df['GPA'].astype(str).str.strip()
            full_grades_df['學分'] = pd.to_numeric(full_grades_df['學分'], errors='coerce').fillna(0)


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
