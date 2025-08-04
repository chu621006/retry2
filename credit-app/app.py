import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

# --- 輔助函數 ---

def normalize_text(cell_content):
    """
    標準化從 pdfplumber 提取的單元格內容。
    處理 None 值、pdfplumber 的 Text 物件和普通字串。
    將多個空白字元（包括換行）替換為單個空格，並去除兩端空白。
    更積極地移除非打印字符。
    """
    if cell_content is None:
        return ""

    text = ""
    if hasattr(cell_content, 'text'):
        text = str(cell_content.text)
    elif isinstance(cell_content, str):
        text = cell_content
    else:
        text = str(cell_content)
    
    # 將所有空白字元（包括換行、tab、多個空格等）替換為單個空格
    text = re.sub(r'\s+', ' ', text)
    # 移除所有非打印 ASCII 字元（例如 NULL, BEL, VT, FF 等）和一些 unicode 控制字元
    text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text) 
    return text.strip()

def identify_gpa_and_credits(text):
    """
    識別文本中的學分和 GPA。
    返回 (學分, GPA) 的 tuple。
    """
    credit = None
    gpa = None

    # 嘗試匹配學分 (例如 2.0, 3, 2.5)
    credit_match = re.search(r'(\d+(\.\d+)?)\s*(學分|credit|點)', text, re.IGNORECASE)
    if credit_match:
        try:
            credit = float(credit_match.group(1))
        except ValueError:
            pass # 轉換失敗則保持 None

    # 嘗試匹配 GPA (例如 4.0, 3.7, A+, B-)
    # GPA 可以是數字，也可以是字母等級
    gpa_match_numeric = re.search(r'(\d(\.\d)?|\d\.\d{2}|[ABCFXabcfx][+\-]?)', text) # 匹配 0.0-4.0 或字母等級
    if gpa_match_numeric:
        gpa_str = gpa_match_numeric.group(1).upper()
        # 排除可能是學分的數字，除非它明顯是GPA (例如4.0)
        if '.' in gpa_str or len(gpa_str) <= 2: # 簡單判斷，數字有小數點，或字母等級通常只有1-2字
             try:
                gpa = float(gpa_str)
             except ValueError:
                gpa = gpa_str # 如果是字母等級，保留字串
        elif len(gpa_str) > 2 and not '.' in gpa_str:
            pass # 如果是長數字且沒有小數點，很可能不是GPA，跳過

    return credit, gpa

def is_grades_table(table, min_rows=5):
    """
    判斷一個 pdfplumber 提取的表格是否為成績表。
    這通過檢查特定類型的欄位（學年、學期、科目名稱、學分、GPA）的內容模式來完成。
    """
    if not table or not table.get("rows"):
        return False, {}, None

    rows = table["rows"]
    if len(rows) < min_rows: # 確保有足夠的資料行來判斷
        return False, {}, None

    # 假設標頭行是第一行，取樣前幾行（或更多）來分析欄位內容
    sample_rows = rows[1:min(len(rows), 10)] # 從第一行（假設是數據）開始取樣，最多10行
    
    # 獲取標頭，並正規化以作為潛在欄位名稱
    header_row = [normalize_text(cell) for cell in rows[0]]
    # 使用唯一的標頭名稱，例如 'Column_1', 'Column_2'
    normalized_columns = {f"Column_{i+1}": col_name for i, col_name in enumerate(header_row)}

    potential_subject_cols = []
    potential_credit_gpa_cols = []
    potential_year_cols = []
    potential_semester_cols = []
    
    # 對每個欄位進行分析
    for col_idx, col_name in normalized_columns.items():
        # 收集該欄位的所有樣本內容
        col_samples = [normalize_text(row[int(col_name.split('_')[1])-1]) for row in sample_rows if len(row) > int(col_name.split('_')[1])-1]
        
        total_sample_count = len(col_samples)
        if total_sample_count == 0:
            continue

        subject_like_cells = 0
        credit_gpa_like_cells = 0
        year_like_cells = 0
        semester_like_cells = 0

        for cell_content in col_samples:
            if not cell_content:
                continue

            # 科目欄位：通常包含中文且非純數字
            if re.search(r'[\u4e00-\u9fff]', cell_content) and not re.fullmatch(r'\d+(\.\d+)?', cell_content):
                subject_like_cells += 1
            
            # 學分/GPA欄位：包含數字或類似GPA的模式 (例如 3.0, A+, 2)
            if re.search(r'(\d+(\.\d+)?|[ABCFXabcfx][+\-]?)', cell_content, re.IGNORECASE):
                credit_gpa_like_cells += 1

            # 學年欄位：例如 111, 109, 2023 (3-4位數字)
            if re.fullmatch(r'\d{3,4}', cell_content):
                year_like_cells += 1
            
            # 學期欄位：包含 '上', '下', '暑'
            if any(s in cell_content for s in ['上', '下', '暑']):
                semester_like_cells += 1
        
        # 判斷是否為潛在的目標欄位，調整閾值
        if subject_like_cells / total_sample_count >= 0.3: # 降低閾值
            potential_subject_cols.append(col_name)
        if credit_gpa_like_cells / total_sample_count >= 0.3: # 降低閾值
            potential_credit_gpa_cols.append(col_name)
        if year_like_cells / total_sample_count >= 0.5: # 降低閾值
            potential_year_cols.append(col_name)
        if semester_like_cells / total_sample_count >= 0.5: # 降低閾值
            potential_semester_cols.append(col_name)

    # 檢查是否至少找到一個科目欄位，以及一個學分/GPA欄位，並試圖找到學年和學期
    if not potential_subject_cols:
        # print("未識別到科目欄位")
        return False, {}, None
    if not potential_credit_gpa_cols:
        # print("未識別到學分/GPA欄位")
        return False, {}, None
    
    # 優先選擇看起來最像的欄位（例如，通常第一個符合條件的就是）
    found_cols = {
        '學年': potential_year_cols[0] if potential_year_cols else None,
        '學期': potential_semester_cols[0] if potential_semester_cols else None,
        '科目名稱': potential_subject_cols[0] if potential_subject_cols else None,
        '學分': None, # GPA和學分可能在同一個欄位，稍後解析
        'GPA': None
    }

    # 針對學分和GPA，從 potential_credit_gpa_cols 中選一個
    # 我們需要找到一個最佳的學分/GPA欄位，這個欄位應該是包含最多學分/GPA資訊的。
    # 這裡可以簡單選第一個，或根據後續實際解析判斷
    if potential_credit_gpa_cols:
        found_cols['學分'] = potential_credit_gpa_cols[0]
        found_cols['GPA'] = potential_credit_gpa_cols[0] # 暫時指向同一個，後續解析

    # 檢查是否所有必要的欄位都被識別
    if not all(found_cols[key] for key in ['科目名稱', '學分', 'GPA']):
        # print("部分核心欄位未識別到")
        # 即使學年學期沒有，只要科目學分GPA有，也算
        if found_cols['科目名稱'] and found_cols['學分']: # 只要有科目和GPA/學分相關欄位就嘗試解析
             return True, found_cols, header_row # 返回原始標頭以便索引
        return False, {}, None

    return True, found_cols, header_row # 返回原始標頭以便索引

def calculate_total_credits(df, grades_mapping):
    """
    計算總學分數和平均 GPA。
    """
    total_credits = 0.0
    weighted_gpa_sum = 0.0
    num_courses_for_gpa = 0

    st.write("--- 計算學分數與 GPA ---")

    for row_idx, row in df.iterrows():
        # 標準化所有單元格內容
        row_content = {k: normalize_text(v) for k, v in row.items()}
        
        # 跳過空行、標頭行或行政性文字
        # 這裡會檢查原始列內容，所以確保原始列在處理前是乾淨的
        original_row_values = list(row.values()) # 獲取原始 Series 的 values
        # 如果原始資料列內容包含學年度、學期等字樣，則跳過，因為這通常是標頭行被錯誤識別
        if any(keyword in original_row_values for keyword in ['學年度', '學期', '選課代號', '科⽬名稱', '學分', 'GPA']):
            st.warning(f"該行被判斷為空行、標頭行或行政性文字，已跳過。原始資料列內容: {original_row_values}")
            continue

        # 更廣泛地檢查跳過條件，例如空行、純粹的頁眉頁腳信息
        if not any(cell.strip() for cell in row_content.values()): # 行中所有單元格都為空
            # st.info(f"該行為空行，已跳過。")
            continue
        # 檢查行政性文字，避免誤判正規課程為行政性文字
        admin_keywords = ['體育室', '本表僅供查詢', '學士班', '研究所', '成績證明', '第', '頁', '總平均', '學業平均']
        if any(keyword in ' '.join(row_content.values()) for keyword in admin_keywords):
            # st.info(f"該行被判斷為行政性文字，已跳過。")
            continue

        # 確保必要的欄位存在
        if not all(k in row_content for k in ['科目名稱', '學分', 'GPA']):
            # st.warning(f"行 {row_idx} 缺少必要的欄位 (科目名稱, 學分, GPA)，已跳過。內容: {row_content}")
            continue

        course_name = row_content.get('科目名稱', '')
        raw_credit_gpa = row_content.get('學分', '') # 由於學分和GPA可能在同一欄位，這裡取其內容

        # 從原始學分/GPA欄位中解析出學分和GPA
        parsed_credit, parsed_gpa = identify_gpa_and_credits(raw_credit_gpa)

        current_credit = parsed_credit
        current_gpa = parsed_gpa

        # 如果單獨的GPA欄位被識別出來，則優先使用其值
        if 'GPA' in row_content and row_content['GPA'] != raw_credit_gpa:
            # 嘗試再次解析以確保正確性
            _, gpa_from_gpa_col = identify_gpa_and_credits(row_content['GPA'])
            if gpa_from_gpa_col is not None:
                current_gpa = gpa_from_gpa_col
        
        # 檢查是否成功解析到學分和 GPA
        if current_credit is None:
            # st.warning(f"科目 '{course_name}' 未能解析到學分，已跳過此科目計算。原始內容: '{raw_credit_gpa}'")
            continue
        
        # 轉換 GPA 為數值 (如果它是字母等級)
        gpa_value = 0.0
        if isinstance(current_gpa, str) and current_gpa in grades_mapping:
            gpa_value = grades_mapping[current_gpa]
        elif isinstance(current_gpa, (float, int)):
            gpa_value = float(current_gpa)
        else:
            # st.warning(f"科目 '{course_name}' 未能解析到有效 GPA 或 GPA 不在對應表中，已跳過此科目計算。原始內容: '{raw_credit_gpa}', 解析結果: '{current_gpa}'")
            continue # 如果 GPA 無效，則不計入 GPA 計算

        # 累加學分和加權 GPA
        total_credits += current_credit
        if gpa_value > 0: # 只有有效 GPA 的科目才計入加權平均
            weighted_gpa_sum += gpa_value * current_credit
            num_courses_for_gpa += 1 # 計數用於確保有實際課程參與GPA計算

    average_gpa = 0.0
    if total_credits > 0: # 使用 total_credits 作為分母來計算平均 GPA
        average_gpa = weighted_gpa_sum / total_credits

    return total_credits, average_gpa

def process_pdf_file(pdf_file, grades_mapping):
    """
    處理上傳的 PDF 檔案，提取表格並計算學分和 GPA。
    """
    all_extracted_data = []

    # 設定 pdfplumber 的表格提取參數
    table_settings = {
        "vertical_strategy": "text", 
        "horizontal_strategy": "text", 
        "snap_tolerance": 15,  # 增大容忍度
        "join_tolerance": 18,  # 增大容忍度
        "edge_min_length": 1,  # 設為更小的值
        "text_tolerance": 7,   # 增大容忍度
        "min_words_vertical": 1, 
        "min_words_horizontal": 1, 
    }

    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page_num, page in enumerate(pdf.pages):
                st.write(f"正在處理頁面: {page_num + 1}")
                # 嘗試從頁面提取表格
                tables = page.extract_tables(table_settings)

                for table_idx, table in enumerate(tables):
                    st.write(f"  偵測到表格 {table_idx + 1}")
                    # 使用 is_grades_table 判斷是否為成績表
                    is_grade_table_result, identified_cols, original_header = is_grades_table(table)

                    if is_grade_table_result:
                        st.success(f"  頁面 {page_num + 1} 的表格 {table_idx + 1} 被識別為成績表。")
                        st.json({"識別到的學年欄位": identified_cols.get('學年'), 
                                 "學期欄位": identified_cols.get('學期'),
                                 "科目欄位": identified_cols.get('科目名稱'), 
                                 "學分欄位": identified_cols.get('學分'), 
                                 "GPA欄位": identified_cols.get('GPA')})

                        # 處理原始表格數據，準備 DataFrame
                        data_rows = []
                        header_map_to_idx = {col_name: i for i, col_name in enumerate(original_header)}
                        
                        # 確保 identified_cols 中的每個識別到的 'Column_X' 都有對應的索引
                        col_mapping = {}
                        for key, col_id in identified_cols.items():
                            if col_id and col_id.startswith('Column_'):
                                try:
                                    # 提取 Column_X 中的數字 X
                                    original_col_idx = int(col_id.split('_')[1]) - 1
                                    col_mapping[key] = original_col_idx
                                except ValueError:
                                    col_mapping[key] = None
                            else:
                                col_mapping[key] = None

                        # 跳過第一行（標頭行），從第二行開始處理數據
                        for row_idx, row_cells in enumerate(table):
                            if row_idx == 0: # 假設第一行是標頭，但在 is_grades_table 中已經處理過
                                continue

                            # 確保行足夠長
                            if not row_cells or len(row_cells) < max(header_map_to_idx.values()) + 1 if header_map_to_idx else 0:
                                continue

                            row_data = {}
                            # 使用識別到的欄位名稱和原始索引來構建行數據
                            for identified_key, original_col_idx in col_mapping.items():
                                if original_col_idx is not None and original_col_idx < len(row_cells):
                                    row_data[identified_key] = normalize_text(row_cells[original_col_idx])
                                else:
                                    row_data[identified_key] = "" # 確保欄位存在，即使為空

                            # 僅當科目名稱不為空時才添加該行
                            if row_data.get('科目名稱'):
                                all_extracted_data.append(row_data)

                    else:
                        st.info(f"  頁面 {page_num + 1} 的表格 {table_idx + 1} 未識別為成績表。原始資料列內容: {table[0] if table else 'N/A'}")
                        st.json({"識別到的學年欄位": identified_cols.get('學年'), 
                                 "學期欄位": identified_cols.get('學期'),
                                 "科目欄位": identified_cols.get('科目名稱'), 
                                 "學分欄位": identified_cols.get('學分'), 
                                 "GPA欄位": identified_cols.get('GPA')})
                        st.warning("該行被判斷為空行、標頭行或行政性文字，已跳過。原始資料列內容: " + str([normalize_text(c) for c in table[0]]))


    except Exception as e:
        st.error(f"處理 PDF 檔案時發生錯誤: {e}")
        return pd.DataFrame(), 0.0, 0.0

    # 將所有提取的數據轉換為 DataFrame
    df = pd.DataFrame(all_extracted_data)
    
    # 確保 DataFrame 中存在所有預期的欄位，如果不存在則添加空欄位
    expected_cols = ['學年', '學期', '科目名稱', '學分', 'GPA']
    for col in expected_cols:
        if col not in df.columns:
            df[col] = ''

    if df.empty:
        st.warning("未從 PDF 中提取到任何有效的成績數據。")
        return pd.DataFrame(), 0.0, 0.0

    # 計算總學分數和平均 GPA
    total_credits, average_gpa = calculate_total_credits(df.copy(), grades_mapping) # 傳遞副本避免修改原始 df

    return df, total_credits, average_gpa

# --- Streamlit 介面 ---
st.title("🎓 GPA 及學分計算器")

st.write("請上傳您的成績單 PDF 檔案，我會為您計算總學分和平均 GPA。")

# 自定義 GPA 等級對應表
st.subheader("設定 GPA 等級對應表")
st.write("請確保您的學校成績等級與此處的 GPA 值對應正確。您可以修改它。")

# 預設 GPA 對應表
default_grades_mapping = {
    'A+': 4.3, 'A': 4.0, 'A-': 3.7,
    'B+': 3.3, 'B': 3.0, 'B-': 2.7,
    'C+': 2.3, 'C': 2.0, 'C-': 1.7,
    'D+': 1.3, 'D': 1.0, 'D-': 0.7,
    'F': 0.0, 'X': 0.0, 'XF': 0.0 # X 或 XF 通常代表不及格
}

# 允許用戶修改對應表
edited_grades_mapping = {}
col1, col2 = st.columns(2)
for i, (grade, gpa_val) in enumerate(default_grades_mapping.items()):
    if i % 2 == 0:
        with col1:
            edited_grades_mapping[grade] = st.number_input(f"{grade} 對應 GPA:", value=gpa_val, key=f"gpa_input_{grade}")
    else:
        with col2:
            edited_grades_mapping[grade] = st.number_input(f"{grade} 對應 GPA:", value=gpa_val, key=f"gpa_input_{grade}")

uploaded_file = st.file_uploader("選擇一個 PDF 檔案", type="pdf")

if uploaded_file is not None:
    st.success(f"檔案 '{uploaded_file.name}' 已成功上傳！")
    
    # 讀取檔案內容到 BytesIO
    pdf_bytes = BytesIO(uploaded_file.getvalue())

    # 處理 PDF 檔案
    with st.spinner("正在處理 PDF，這可能需要一些時間..."):
        df_grades, total_credits, average_gpa = process_pdf_file(pdf_bytes, edited_grades_mapping)
    
    if not df_grades.empty:
        st.subheader("提取到的成績數據 (部分預覽)")
        st.dataframe(df_grades)

        st.subheader("計算結果")
        st.metric("總學分數", f"{total_credits:.2f}")
        st.metric("平均 GPA", f"{average_gpa:.2f}")
    else:
        st.error("未能從上傳的 PDF 檔案中提取到任何有效的成績數據。請檢查檔案格式或嘗試其他檔案。")
        st.info("提示：確保您的 PDF 成績單是文字可選取的，而不是圖片掃描件。")

st.markdown("---")
st.write("如果您遇到任何問題，請檢查原始程式碼或提供更多詳細資訊。")
