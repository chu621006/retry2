import streamlit as st
import pandas as pd
import io
import pdfplumber
import re

# --- 1. 定義輔助函數 ---

def normalize_text(text):
    """
    標準化文本：移除換行符、全形空格，並修剪空白。
    """
    if text is None:
        return ""
    text = str(text) # 確保輸入是字串
    # 移除換行符、回車符，並將全形空格轉換為半形空格，然後修剪前後空白
    text = text.replace('\n', ' ').replace('\r', '').replace('\u3000', ' ').strip()
    # 針對中文標點符號的替換，這部分您之前可能有定義，這裡可以保留或添加
    text = text.replace('，', ',').replace('。', '.').replace('：', ':').replace('；', ';')
    text = text.replace('　', ' ') # 再次處理全形空格
    return text

def parse_gpa_to_numeric(gpa_str):
    """
    將 GPA 字串轉換為數值，處理特殊值如 '抵免' 和 '通過'。
    """
    gpa_str = normalize_text(gpa_str)
    gpa_mapping = {
        'A+': 4.3, 'A': 4.0, 'A-': 3.7,
        'B+': 3.3, 'B': 3.0, 'B-': 2.7,
        'C+': 2.3, 'C': 2.0, 'C-': 1.7,
        # 'D+': 1.3, 'D': 1.0, 'D-': 0.7, # 根據您的說明，D 為不及格，不計入學分，但為保留原始GPA值，此處仍保留映射
        'D+': 0.0, 'D': 0.0, 'D-': 0.0, # 假設 D 等級不計入有效GPA計算
        'E': 0.0, 'F': 0.0, 'X': 0.0,
        '抵免': 0.0, '通過': 0.0, '': 0.0, 'None': 0.0
    }
    return gpa_mapping.get(gpa_str, 0.0)

def parse_gpa_credit_from_combined_cell(gpa_cell_content, credit_cell_content):
    """
    處理 GPA 和學分可能合併在一個單元格，或提取不正確的情況。
    返回清理後的 GPA 和學分值。
    """
    # 確保所有輸入都是字串並正規化
    original_gpa_str = normalize_text(gpa_cell_content)
    original_credit_str = normalize_text(credit_cell_content)

    parsed_gpa = original_gpa_str
    parsed_credit = original_credit_str

    # 定義一個正則表達式來匹配可能的成績和學分數字
    # 允許成績部分包含字母、+/-、中文的抵免/通過，數字部分包含數字和點
    # (\S*) 匹配非空白字符作為成績部分（盡可能多）
    # (\d*\.?\d*) 匹配數字或浮點數作為學分部分
    grade_credit_pattern = re.compile(r'^\s*([A-Z\+\-\u4F5C\u4F4D\u62B5\u514D\u901A\u904E]*)\s*(\d*\.?\d*)\s*$')
    # 這裡額外加入了 "作" "位" 是為了處理 "抵免" 的簡體字問題，可以根據實際情況調整

    # 嘗試從原始 GPA 單元格解析
    match_gpa_cell = grade_credit_pattern.match(original_gpa_str)
    # 嘗試從原始 Credit 單元格解析
    match_credit_cell = grade_credit_pattern.match(original_credit_str)

    # 情況1：學分單元格是空的或看起來像成績，嘗試從 GPA 單元格解析
    # 如果原始學分看起來不像數字，且原始 GPA 單元格有內容
    if (not original_credit_str.replace('.', '', 1).isdigit() and original_gpa_str):
        if match_gpa_cell:
            grade_part_g = match_gpa_cell.group(1).strip()
            num_part_g = match_gpa_cell.group(2).strip()

            # 如果 GPA 單元格包含成績和數字，並且學分單元格是空的或只有成績
            if (parse_gpa_to_numeric(grade_part_g) != 0.0 or grade_part_g in ['抵免', '通過']) and num_part_g.replace('.', '', 1).isdigit():
                parsed_gpa = grade_part_g
                parsed_credit = num_part_g
            # 如果 GPA 單元格只有成績
            elif (parse_gpa_to_numeric(grade_part_g) != 0.0 or grade_part_g in ['抵免', '通過']) and not num_part_g:
                parsed_gpa = grade_part_g
                parsed_credit = original_credit_str if original_credit_str.replace('.', '', 1).isdigit() else '' # 確保學分還是數字
            # 如果 GPA 單元格只有數字
            elif num_part_g.replace('.', '', 1).isdigit() and not grade_part_g:
                parsed_credit = num_part_g
                parsed_gpa = original_gpa_str if (parse_gpa_to_numeric(original_gpa_str) != 0.0 or original_gpa_str in ['抵免', '通過']) else ''


    # 情況2：GPA 單元格是空的或看起來像學分數字，嘗試從 Credit 單元格解析
    # 如果原始 GPA 看起來不像成績，且原始 Credit 單元格有內容
    if (not (parse_gpa_to_numeric(original_gpa_str) != 0.0 or original_gpa_str in ['抵免', '通過']) and original_credit_str):
        if match_credit_cell:
            grade_part_c = match_credit_cell.group(1).strip()
            num_part_c = match_credit_cell.group(2).strip()

            # 如果 Credit 單元格包含成績和數字，並且 GPA 單元格是空的或只有學分
            if (parse_gpa_to_numeric(grade_part_c) != 0.0 or grade_part_c in ['抵免', '通過']) and num_part_c.replace('.', '', 1).isdigit():
                parsed_gpa = grade_part_c
                parsed_credit = num_part_c
            # 如果 Credit 單元格只有成績
            elif (parse_gpa_to_numeric(grade_part_c) != 0.0 or grade_part_c in ['抵免', '通過']) and not num_part_c:
                parsed_gpa = grade_part_c
                parsed_credit = original_credit_str if original_credit_str.replace('.', '', 1).isdigit() else ''
            # 如果 Credit 單元格只有數字
            elif num_part_c.replace('.', '', 1).isdigit() and not grade_part_c:
                parsed_credit = num_part_c
                parsed_gpa = original_gpa_str if (parse_gpa_to_numeric(original_gpa_str) != 0.0 or original_gpa_str in ['抵免', '通過']) else ''


    # 最終校驗：確保 GPA 是成績格式，學分是數字格式
    final_gpa = parsed_gpa
    final_credit = parsed_credit

    is_gpa_format = (parse_gpa_to_numeric(final_gpa) != 0.0 or final_gpa in ['抵免', '通過']) and not final_gpa.replace('.', '', 1).isdigit()
    is_credit_format = final_credit.replace('.', '', 1).isdigit()

    # 如果 GPA 欄位是數字格式，學分欄位是成績格式，則交換
    if final_gpa.replace('.', '', 1).isdigit() and (parse_gpa_to_numeric(final_credit) != 0.0 or final_credit in ['抵免', '通過']):
        final_gpa, final_credit = final_credit, final_gpa

    # 如果解析結果不是預期的格式，盡可能使用原始值（如果原始值符合單一格式）
    if not is_gpa_format and (parse_gpa_to_numeric(original_gpa_str) != 0.0 or original_gpa_str in ['抵免', '通過']):
        final_gpa = original_gpa_str
    if not is_credit_format and original_credit_str.replace('.', '', 1).isdigit():
        final_credit = original_credit_str

    # 確保返回的學分是空字串或數字字串
    if not final_credit.replace('.', '', 1).isdigit() and final_credit != '':
        final_credit = '' # 如果最終學分不是數字，則清空

    return final_gpa, final_credit

def analyze_student_grades(df):
    """
    分析學生的成績 DataFrame，計算總學分、所需學分和通過的課程。
    """
    if df.empty:
        return 0, 128, pd.DataFrame(columns=['學年度', '學期', '科目名稱', '學分', 'GPA'])

    # 確保 GPA 和 學分 欄位是正確的數據類型
    df['GPA_Numeric'] = df['GPA'].apply(parse_gpa_to_numeric)
    # 將 '學分' 轉換為數值，無法轉換的設為 NaN，然後填充為 0
    df['學分'] = pd.to_numeric(df['學分'], errors='coerce').fillna(0)

    # 假設通過的標準是 GPA > 0 (A+到C-)，或為 '抵免' 或 '通過'，且學分大於 0
    # 根據您的需求，'D' 等級的 GPA_Numeric 為 0，因此不會被計入
    passed_courses_df = df[
        ((df['GPA_Numeric'] > 0) | (df['GPA'].isin(['抵免', '通過']))) &
        (df['學分'] > 0) # 確保學分大於 0 且不是勞作教育（已在前面過濾）
    ].copy() # 使用 .copy() 避免 SettingWithCopyWarning

    total_credits = passed_courses_df['學分'].sum()
    required_credits = 128
    remaining_credits = max(0, required_credits - total_credits)

    return total_credits, remaining_credits, passed_courses_df

# --- Streamlit 應用程式主體 ---
def main():
    st.title("總學分查詢系統 🎓")
    st.write("請上傳您的成績總表 PDF 檔案，系統將會為您查詢目前總學分與距離畢業所需的學分。")
    st.info("💡 確保您的成績單 PDF 是清晰的表格格式，以獲得最佳解析效果。")

    uploaded_file = st.file_uploader("上傳成績總表 PDF 檔案", type=["pdf"])

    # 確保 all_grades_data 和 full_grades_df 在 main 函數開始時被初始化
    all_grades_data = []  # 每次上傳檔案時重新初始化
    full_grades_df = pd.DataFrame()  # 每次上傳檔案時重新初始化

    if uploaded_file is not None:
        st.success("檔案上傳成功！正在分析中...")

        try:
            expected_header_keywords = ["學年度", "學期", "選課代號", "科目名稱", "學分", "GPA"]
            
            with pdfplumber.open(io.BytesIO(uploaded_file.getvalue())) as pdf:
                total_pages = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages):
                    st.write(f"正在處理頁面 {page_num + 1}/{total_pages}...") # 增加進度顯示
                    top_y_crop = 0
                    bottom_y_crop = page.height

                    # 針對特定檔案名調整裁剪高度，可以嘗試更寬鬆的範圍或統一處理
                    # 這裡統一設置一個較大的裁剪範圍，如果仍有問題，再考慮更精確調整
                    if "謝云瑄成績總表.pdf" in uploaded_file.name:
                        # 謝雲萱的 PDF 首頁和後續頁面的裁剪Y軸差異不大，可以嘗試統一
                        top_y_crop = 120 # 降低一點點，減少切到表格的風險
                        bottom_y_crop = page.height - 30
                    elif "邱旭廷成績總表.pdf" in uploaded_file.name:
                        # 邱旭廷的 PDF 首頁可能需要更高的裁剪
                        top_y_crop = 200 if page_num == 0 else 80 # 稍微調低點
                        bottom_y_crop = page.height - 30
                    else: # 預設通用設置
                        top_y_crop = 100 if page_num == 0 else 50
                        bottom_y_crop = page.height - 30

                    cropped_page = page.crop((0, top_y_crop, page.width, bottom_y_crop))
                    
                    # 調整 table_settings，增加容忍度，提高提取成功率
                    table_settings = {
                        "vertical_strategy": "lines",
                        "horizontal_strategy": "lines",
                        "snap_tolerance": 3,  # 增加容忍度
                        "text_tolerance": 3,  # 增加容忍度
                        "join_tolerance": 3,  # 增加容忍度
                        "edge_min_length": 5, # 稍微增加最小線段長度
                        "min_words_horizontal": 1,
                        "min_words_vertical": 1,
                        "snap_vertical": None, # 讓 pdfplumber 自動判斷
                        "snap_horizontal": None # 讓 pdfplumber 自動判斷
                    }
                    
                    tables = cropped_page.extract_tables(table_settings)
                    
                    if not tables:
                        st.write(f"頁面 {page_num + 1}: 未能提取到任何表格。")
                        continue

                    for table_idx, table in enumerate(tables):
                        if not table or len(table) < 1:
                            continue

                        filtered_table = []
                        for row in table:
                            # 確保 cell 是字串，並呼叫 normalize_text
                            normalized_row = [normalize_text(cell) for cell in row]  
                            if any(cell.strip() for cell in normalized_row):
                                filtered_table.append(normalized_row)
                        
                        if not filtered_table:
                            st.write(f"頁面 {page_num + 1}, 表格 {table_idx + 1}: 過濾後無有效數據。")
                            continue
                        
                        header_row_found = False
                        header = []
                        header_row_start_idx = -1

                        potential_header_search_range = min(len(filtered_table), 5)
                        for h_idx in range(potential_header_search_range):
                            h_row_cells = [cell.strip() for cell in filtered_table[h_idx]]
                            
                            # 強化表頭匹配，使用正則表達式或更寬鬆的包含檢查
                            header_match_criteria = [
                                any(re.search(r'學年', cell) for cell in h_row_cells),
                                any(re.search(r'科目名稱', cell) for cell in h_row_cells),
                                any(re.search(r'學分', cell) for cell in h_row_cells),
                                any(re.search(r'GPA', cell) for cell in h_row_cells)
                            ]

                            if all(header_match_criteria):
                                header = h_row_cells
                                header_row_found = True
                                header_row_start_idx = h_idx
                                st.write(f"頁面 {page_num + 1}, 表格 {table_idx + 1}: 找到表頭。")
                                break
                        
                        if not header_row_found:
                            # 備用方案：如果第一行看起來像數據（學年度是三位數字），則假設第一行為數據行
                            if len(filtered_table[0]) > 0 and filtered_table[0][0].isdigit() and len(filtered_table[0][0]) == 3:
                                header = expected_header_keywords # 使用預期表頭作為列名
                                header_row_start_idx = -1 # 表示沒有明確表頭行，數據從第一行開始
                                header_row_found = True
                                st.write(f"頁面 {page_num + 1}, 表格 {table_idx + 1}: 未找到明確表頭，假定第一行是數據。")
                            else:
                                st.warning(f"頁面 {page_num + 1}, 表格 {table_idx + 1}: 未能識別表頭或有效數據行，跳過此表格。")
                                continue

                        col_to_index = {}
                        for i, h_text in enumerate(header):
                            # 使用更寬鬆的匹配來找到列索引
                            if re.search(r'學年', h_text): col_to_index["學年度"] = i
                            elif re.search(r'學期', h_text): col_to_index["學期"] = i
                            elif re.search(r'代號', h_text): col_to_index["選課代號"] = i
                            elif re.search(r'科目名稱', h_text): col_to_index["科目名稱"] = i
                            elif re.search(r'學分', h_text): col_to_index["學分"] = i
                            elif re.search(r'GPA', h_text): col_to_index["GPA"] = i

                        critical_cols = ["學年度", "科目名稱", "學分", "GPA"]
                        if not all(col in col_to_index for col in critical_cols):
                            st.warning(f"頁面 {page_num + 1} 的表格 {table_idx + 1} 缺少關鍵列。跳過此表格。")
                            continue

                        # 從 col_to_index 安全地獲取索引
                        學年度_idx = col_to_index.get("學年度")
                        學期_idx = col_to_index.get("學期")
                        選課代號_idx = col_to_index.get("選課代號")
                        科目名稱_idx = col_to_index.get("科目名稱")
                        學分_idx = col_to_index.get("學分")
                        GPA_idx = col_to_index.get("GPA")

                        processed_rows = []
                        current_row_data_temp = {key: "" for key in expected_header_keywords} # 使用字典存儲，更健壯

                        data_rows_to_process = filtered_table[header_row_start_idx + 1:] if header_row_start_idx != -1 else filtered_table[:]

                        for row_num_in_table, row_cells in enumerate(data_rows_to_process):
                            # 確保 row_cells_padded 足夠長，以防索引越界
                            max_idx_needed = max( 學年度_idx if 學年度_idx is not None else -1,
                                                學期_idx if 學期_idx is not None else -1,
                                                選課代號_idx if 選課代號_idx is not None else -1,
                                                科目名稱_idx if 科目名稱_idx is not None else -1,
                                                學分_idx if 學分_idx is not None else -1,
                                                GPA_idx if GPA_idx is not None else -1)

                            row_cells_padded = row_cells + [''] * (max_idx_needed + 1 - len(row_cells))

                            # 安全地獲取每個單元格的值
                            學年度_val = normalize_text(row_cells_padded[學年度_idx]) if 學年度_idx is not None and 學年度_idx < len(row_cells_padded) else ''
                            學期_val = normalize_text(row_cells_padded[學期_idx]) if 學期_idx is not None and 學期_idx < len(row_cells_padded) else ''
                            選課代號_val = normalize_text(row_cells_padded[選課代號_idx]) if 選課代號_idx is not None and 選課代號_idx < len(row_cells_padded) else ''
                            科目名稱_val = normalize_text(row_cells_padded[科目名稱_idx]) if 科目名稱_idx is not None and 科目名稱_idx < len(row_cells_padded) else ''
                            學分_val_raw = normalize_text(row_cells_padded[學分_idx]) if 學分_idx is not None and 學分_idx < len(row_cells_padded) else ''
                            GPA_val_raw = normalize_text(row_cells_padded[GPA_idx]) if GPA_idx is not None and GPA_idx < len(row_cells_padded) else ''

                            is_new_grade_row = False
                            # 判斷是否為新的課程行：學年度是三位數字，且科目名稱不為空
                            # 減少對選課代號的依賴，因為它可能在某些行中是空的
                            if 學年度_val.isdigit() and len(學年度_val) == 3 and 科目名稱_val.strip() != '':
                                is_new_grade_row = True
                            
                            # 或者，如果科目名稱不為空，且前兩個欄位都為空，也可能是一個新行（針對跨頁的第一次出現）
                            elif 學年度_val.strip() == '' and 學期_val.strip() == '' and 科目名稱_val.strip() != '':
                                # 判斷這是否是一個應該獨立的新行，而不是前一行的延續
                                # 如果本行有學分或GPA，更可能是新行
                                if 學分_val_raw.strip() != '' or GPA_val_raw.strip() != '':
                                    is_new_grade_row = True

                            if is_new_grade_row:
                                # 如果已經有正在處理的行數據，先將其添加到 processed_rows
                                if current_row_data_temp['科目名稱'].strip() != "": # 確保有實際內容才添加
                                    processed_rows.append(list(current_row_data_temp.values())) # 轉為列表再添加
                                
                                # 開始處理新的行
                                current_row_data_temp = {key: "" for key in expected_header_keywords}
                                current_row_data_temp["學年度"] = 學年度_val
                                current_row_data_temp["學期"] = 學期_val
                                current_row_data_temp["選課代號"] = 選課代號_val
                                current_row_data_temp["科目名稱"] = 科目名稱_val
                                
                                current_gpa, current_credit = parse_gpa_credit_from_combined_cell(GPA_val_raw, 學分_val_raw)
                                current_row_data_temp["GPA"] = current_gpa
                                current_row_data_temp["學分"] = current_credit

                            elif current_row_data_temp['科目名稱'].strip() != "": # 如果不是新行，則可能是前一行的延續
                                # 判斷是否為科目名稱的延續行
                                if 學年度_val.strip() == '' and 學期_val.strip() == '' and 選課代號_val.strip() == '' and 科目名稱_val.strip() != '':
                                    current_row_data_temp["科目名稱"] += " " + 科目名稱_val
                                
                                # 對於延續行，如果學分或 GPA 被找到，則更新
                                # 避免覆蓋已經存在的有效值，只在當前為空時更新
                                if (學分_val_raw.strip() != '' or GPA_val_raw.strip() != ''):
                                    merged_gpa, merged_credit = parse_gpa_credit_from_combined_cell(GPA_val_raw, 學分_val_raw)
                                    
                                    if current_row_data_temp["學分"].strip() == "" and merged_credit.strip() != "":
                                        current_row_data_temp["學分"] = merged_credit
                                    if current_row_data_temp["GPA"].strip() == "" and merged_gpa.strip() != "":
                                        current_row_data_temp["GPA"] = merged_gpa

                        # 將最後一行的數據添加到 processed_rows
                        if current_row_data_temp['科目名稱'].strip() != "":
                            processed_rows.append(list(current_row_data_temp.values()))
                        
                        if processed_rows:
                            df_table = pd.DataFrame(processed_rows, columns=expected_header_keywords)
                            
                            # 對 DataFrame 中的所有列進行最終的字串清理
                            for col in df_table.columns:
                                df_table[col] = df_table[col].astype(str).str.strip().replace('None', '').replace('nan', '')

                            all_grades_data.append(df_table)
                        else:
                            st.write(f"頁面 {page_num + 1}, 表格 {table_idx + 1}: 沒有可處理的課程數據。")

            if not all_grades_data:
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式或調整表格提取設定。")
                full_grades_df = pd.DataFrame(columns=expected_header_keywords)
            else:
                full_grades_df = pd.concat(all_grades_data, ignore_index=True)

                # 進一步清理 DataFrame
                full_grades_df.dropna(how='all', inplace=True)
                
                # 過濾掉不符合學年度和選課代號模式的行
                # 學年度必須是三位數字，科目名稱不能為空，選課代號可以為空但不能是雜質
                if '學年度' in full_grades_df.columns and '科目名稱' in full_grades_df.columns:
                    full_grades_df = full_grades_df[
                        full_grades_df['學年度'].astype(str).str.match(r'^\d{3}$') &
                        (full_grades_df['科目名稱'].astype(str).str.strip() != '') &
                        (~full_grades_df['科目名稱'].astype(str).str.contains(r'^\s*$', na=False)) # 確保科目名稱不是全空白
                    ]
                
                # 過濾掉「勞作成績」
                if '科目名稱' in full_grades_df.columns:
                    full_grades_df = full_grades_df[~full_grades_df['科目名稱'].astype(str).str.contains('勞作', na=False)] # 更廣泛地匹配“勞作”
                
                # 確保 GPA 欄位是字串並修剪
                if 'GPA' in full_grades_df.columns:
                    full_grades_df['GPA'] = full_grades_df['GPA'].astype(str).str.strip()
                
                # 將學分轉換為數值，非數字的設為0
                if '學分' in full_grades_df.columns:
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
            st.exception(e) # 顯示完整的錯誤追蹤，方便除錯

if __name__ == "__main__":
    main()
