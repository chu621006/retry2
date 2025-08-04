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
    同時處理「抵免」和「通過」情況，這些情況通常有學分但無實際GPA數值。
    """
    credit = None
    gpa = None
    original_text = text # 保存原始文本用於判斷

    # 檢查是否為「抵免」或「通過」的課程
    if "抵免" in original_text:
        # 從抵免文字中嘗試提取學分，否則預設為0.0或根據學校規則
        # 例如：抵免 3 學分
        credit_match_defer = re.search(r'(\d+(\.\d+)?)\s*抵免', original_text)
        if credit_match_defer:
            try:
                credit = float(credit_match_defer.group(1))
            except ValueError:
                credit = 0.0 # 若解析不到，預設為0學分
        else:
            credit = 0.0 # 預設抵免的課程學分為0，具體根據學校政策調整
        gpa = "抵免" # GPA 設置為特殊標記
        return credit, gpa
    
    if "通過" in original_text:
        # 從通過文字中嘗試提取學分，否則預設為0.0或根據學校規則
        credit_match_pass = re.search(r'(\d+(\.\d+)?)\s*通過', original_text)
        if credit_match_pass:
            try:
                credit = float(credit_match_pass.group(1))
            except ValueError:
                credit = 0.0 # 若解析不到，預設為0學分
        else:
            credit = 0.0 # 預設通過的課程學分為0，具體根據學校政策調整
        gpa = "通過" # GPA 設置為特殊標記
        return credit, gpa


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

    # 獲取標頭，並正規化以作為潛在欄位名稱
    header_row_raw = rows[0]
    header_row_normalized = [normalize_text(cell) for cell in header_row_raw]

    # 使用唯一的標頭名稱，例如 'Column_1', 'Column_2'
    normalized_columns = {f"Column_{i+1}": col_name for i, col_name in enumerate(header_row_normalized)}

    # --- 第一階段：依據標頭文字直接匹配 ---
    identified_cols_by_header = {}
    
    # 學年欄位 (優先匹配完整關鍵字，再匹配部分關鍵字)
    year_keywords_full = ['學年度', '學年']
    year_keywords_partial = ['學年 度', '學年'] # 包含手機端可能的變體
    for col_id, col_name in normalized_columns.items():
        if any(keyword in col_name for keyword in year_keywords_full):
            identified_cols_by_header['學年'] = col_id
            break
    if '學年' not in identified_cols_by_header: # 如果完整關鍵字沒找到，嘗試部分關鍵字
        for col_id, col_name in normalized_columns.items():
            if any(keyword in col_name for keyword in year_keywords_partial):
                identified_cols_by_header['學年'] = col_id
                break
            
    # 學期欄位
    semester_keywords_full = ['學期']
    semester_keywords_partial = ['學 期', '學期'] # 包含手機端可能的變體
    for col_id, col_name in normalized_columns.items():
        if any(keyword in col_name for keyword in semester_keywords_full):
            identified_cols_by_header['學期'] = col_id
            break
    if '學期' not in identified_cols_by_header: # 如果完整關鍵字沒找到，嘗試部分關鍵字
        for col_id, col_name in normalized_columns.items():
            if any(keyword in col_name for keyword in semester_keywords_partial):
                identified_cols_by_header['學期'] = col_id
                break

    # 科目名稱欄位
    subject_keywords = ['科目名稱', '科目', '課程名稱', '課程']
    for col_id, col_name in normalized_columns.items():
        if any(keyword in col_name for keyword in subject_keywords):
            identified_cols_by_header['科目名稱'] = col_id
            break

    # 學分欄位
    credit_keywords = ['學分', '學分數', 'Credits', '學 分'] # 增加手機端可能的變體
    for col_id, col_name in normalized_columns.items():
        if any(keyword in col_name for keyword in credit_keywords):
            identified_cols_by_header['學分'] = col_id
            # 暫時將GPA也指向學分欄位，後續再從內容解析
            identified_cols_by_header['GPA'] = col_id 
            break

    # GPA 欄位 (如果存在獨立的 GPA 欄位)
    gpa_keywords = ['GPA', '平均成績', 'Grade']
    for col_id, col_name in normalized_columns.items():
        if any(keyword in col_name for keyword in gpa_keywords):
            # 如果學分和GPA都被識別到同一欄位，且這次找到了明確的GPA欄位，更新GPA欄位
            if '學分' in identified_cols_by_header and identified_cols_by_header['學分'] == col_id:
                pass # 保持原樣或在下一階段內容判斷時修正
            else:
                identified_cols_by_header['GPA'] = col_id
            break

    # 如果已經透過標頭識別到所有核心欄位，則直接返回
    if identified_cols_by_header.get('科目名稱') and \
       identified_cols_by_header.get('學分') and \
       identified_cols_by_header.get('GPA'):
        # 確保學分和GPA至少有一個被明確識別
        if identified_cols_by_header['學分'] or identified_cols_by_header['GPA']:
            return True, identified_cols_by_header, header_row_normalized


    # --- 第二階段：若標頭匹配不完整，則使用內容模式輔助判斷 ---
    # 僅在未完全識別核心欄位時才執行此階段
    if not (identified_cols_by_header.get('科目名稱') and \
            identified_cols_by_header.get('學分') and \
            identified_cols_by_header.get('GPA')):

        sample_rows = rows[1:min(len(rows), 10)] # 從第一行（假設是數據）開始取樣，最多10行
        
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
                if re.search(r'(\d+(\.\d+)?|[ABCFXabcfx][+\-]?)', cell_content, re.IGNORECASE) or \
                   ("抵免" in cell_content) or ("通過" in cell_content): # 增加對「抵免」和「通過」的判斷
                    credit_gpa_like_cells += 1

                # 學年欄位：例如 111, 109, 2023 (3-4位數字)
                if re.fullmatch(r'\d{3,4}', cell_content):
                    year_like_cells += 1
                
                # 學期欄位：包含 '上', '下', '暑'
                if any(s in cell_content for s in ['上', '下', '暑']):
                    semester_like_cells += 1
            
            # 判斷是否為潛在的目標欄位，將結果合併到 identified_cols_by_header
            if subject_like_cells / total_sample_count >= 0.3 and '科目名稱' not in identified_cols_by_header: 
                identified_cols_by_header['科目名稱'] = col_id
            if credit_gpa_like_cells / total_sample_count >= 0.3 and '學分' not in identified_cols_by_header: 
                identified_cols_by_header['學分'] = col_id
                # 如果還沒有明確的GPA欄位，暫時將GPA也指向這個欄位
                if 'GPA' not in identified_cols_by_header:
                    identified_cols_by_header['GPA'] = col_id
            if year_like_cells / total_sample_count >= 0.5 and '學年' not in identified_cols_by_header: 
                identified_cols_by_header['學年'] = col_id
            if semester_like_cells / total_sample_count >= 0.5 and '學期' not in identified_cols_by_header: 
                identified_cols_by_header['學期'] = col_id

    # 最終檢查是否所有必要的欄位都被識別
    # 只要科目和學分/GPA的至少一個被識別，就認為是成績表
    if identified_cols_by_header.get('科目名稱') and \
       (identified_cols_by_header.get('學分') or identified_cols_by_header.get('GPA')):
        return True, identified_cols_by_header, header_row_normalized
    
    return False, {}, None

def calculate_total_credits(df, grades_mapping):
    """
    計算總學分數和平均 GPA。
    現在會將「抵免」和「通過」的課程學分計入總學分，但不計入 GPA 平均。
    """
    total_credits = 0.0
    weighted_gpa_sum = 0.0
    num_courses_for_gpa = 0

    st.write("--- 計算學分數與 GPA ---")

    # 用于存放通過的和不及格的科目列表
    calculated_courses = []
    failed_courses = []

    for row_idx, row in df.iterrows():
        # 標準化所有單元格內容
        row_content = {k: normalize_text(v) for k, v in row.items()}
        
        # 重新檢查，確保沒有 header-like 的內容被當作數據行
        # 這裡的 `row_content` 已經是經過 `normalize_text` 處理的
        header_keywords = ['學年 度', '學 期', '選課代 號', '科目名稱', '學 分', 'GPA', '學年度', '學期', '選課代號']
        if any(keyword in str(v) for v in row_content.values() for keyword in header_keywords if v):
            st.warning(f"該行被判斷為標頭行或行政性文字，已跳過。原始資料列內容: {list(row_content.values())}")
            continue

        # 更廣泛地檢查跳過條件，例如空行、純粹的頁眉頁腳信息
        if not any(cell.strip() for cell in row_content.values()): # 行中所有單元格都為空
            continue
        # 檢查行政性文字，避免誤判正規課程為行政性文字
        admin_keywords = ['體育室', '本表僅供查詢', '學士班', '研究所', '成績證明', '第', '頁', '總平均', '學業平均', '網頁', '共計'] # 增加“共計”以跳過總結行
        if any(keyword in ' '.join(row_content.values()) for keyword in admin_keywords):
            continue

        # 確保必要的欄位存在
        if not all(k in row_content for k in ['科目名稱', '學分', 'GPA']):
            continue

        course_name = row_content.get('科目名稱', '')
        raw_credit_gpa_content = row_content.get('學分', '') 

        # 從原始學分/GPA欄位中解析出學分和GPA
        parsed_credit, parsed_gpa = identify_gpa_and_credits(raw_credit_gpa_content)

        current_credit = parsed_credit
        current_gpa = parsed_gpa

        # 如果單獨的GPA欄位被識別出來，則優先使用其值
        if 'GPA' in row_content and row_content['GPA'] and row_content['GPA'] != raw_credit_gpa_content:
            _, gpa_from_gpa_col = identify_gpa_and_credits(row_content['GPA'])
            if gpa_from_gpa_col is not None:
                current_gpa = gpa_from_gpa_col
        
        # 處理學分 (即使 GPA 無效，學分也可能有效)
        if current_credit is None:
            # 如果學分解析失敗，但在原始文本中能找到類似數字的值，嘗試強制轉換
            credit_num_match = re.search(r'(\d+(\.\d+)?)', raw_credit_gpa_content)
            if credit_num_match:
                try:
                    current_credit = float(credit_num_match.group(1))
                except ValueError:
                    current_credit = 0.0 # 最終仍無法解析，設為0
            else:
                current_credit = 0.0 # 預設為0，不計入總學分

        # 對於抵免或通過的課程，學分計入總學分，但 GPA 不計入平均
        if current_gpa in ["抵免", "通過"]:
            total_credits += current_credit
            # 這類課程不計入 GPA 平均
            calculated_courses.append({
                '學年': row_content.get('學年', ''),
                '學期': row_content.get('學期', ''),
                '科目名稱': course_name,
                '學分': current_credit,
                'GPA': current_gpa,
                '狀態': current_gpa # 標記為抵免或通過
            })
            continue # 跳過後續的 GPA 計算部分

        # 轉換 GPA 為數值 (如果它是字母等級)
        gpa_value = 0.0
        if isinstance(current_gpa, str) and current_gpa in grades_mapping:
            gpa_value = grades_mapping[current_gpa]
        elif isinstance(current_gpa, (float, int)):
            gpa_value = float(current_gpa)
        else:
            # 如果 GPA 無效，則不計入 GPA 計算，但學分仍計入總學分
            calculated_courses.append({
                '學年': row_content.get('學年', ''),
                '學期': row_content.get('學期', ''),
                '科目名稱': course_name,
                '學分': current_credit,
                'GPA': current_gpa, # 顯示解析到的原始GPA
                '狀態': 'GPA 無效'
            })
            total_credits += current_credit
            continue 

        # 累加學分和加權 GPA
        total_credits += current_credit
        if gpa_value > 0: # 只有有效 GPA 的科目才計入加權平均 (F通常為0)
            weighted_gpa_sum += gpa_value * current_credit
            num_courses_for_gpa += 1 # 計數用於確保有實際課程參與GPA計算

        # 判斷是否為不及格科目 (GPA <= D-)
        is_failed = False
        if isinstance(current_gpa, str) and current_gpa.upper() in ['F', 'X', 'XF', 'E']:
            is_failed = True
        elif isinstance(gpa_value, (float, int)) and gpa_value < grades_mapping.get('D', 1.0): # D- 可能低於1.0
            is_failed = True

        course_info = {
            '學年': row_content.get('學年', ''),
            '學期': row_content.get('學期', ''),
            '科目名稱': course_name,
            '學分': current_credit,
            'GPA': current_gpa,
            'GPA數值': gpa_value # 添加GPA數值方便查看
        }
        
        if is_failed:
            course_info['狀態'] = '不及格'
            failed_courses.append(course_info)
        else:
            course_info['狀態'] = '通過'
            calculated_courses.append(course_info)

    average_gpa = 0.0
    # 確保只有當有科目參與 GPA 計算時才進行除法，避免除以零
    if num_courses_for_gpa > 0: 
        average_gpa = weighted_gpa_sum / (total_credits if total_credits > 0 else 1) # 這裡用total_credits可能不準，應使用 num_courses_for_gpa_credits

    # 重新計算 num_courses_for_gpa_credits
    gpa_relevant_credits = 0.0
    for course in calculated_courses:
        if course['狀態'] == '通過': # 假設只有「通過」的課程才計算GPA，排除抵免/無效GPA
            if isinstance(course['GPA數值'], (float, int)) and course['GPA數值'] > 0: # 確保GPA有效且非0
                 gpa_relevant_credits += course['學分']
    
    if gpa_relevant_credits > 0:
        average_gpa = weighted_gpa_sum / gpa_relevant_credits
    else:
        average_gpa = 0.0


    return total_credits, average_gpa, calculated_courses, failed_courses

def process_pdf_file(pdf_file, grades_mapping):
    """
    處理上傳的 PDF 檔案，提取表格並計算學分和 GPA。
    """
    all_extracted_data = [] # 用於存儲所有行的原始字典數據

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
                    is_grade_table_result, identified_cols, original_header_normalized = is_grades_table(table)

                    if is_grade_table_result:
                        st.success(f"  頁面 {page_num + 1} 的表格 {table_idx + 1} 被識別為成績表。")
                        st.json({"識別到的學年欄位": identified_cols.get('學年'), 
                                 "學期欄位": identified_cols.get('學期'),
                                 "科目欄位": identified_cols.get('科目名稱'), 
                                 "學分欄位": identified_cols.get('學分'), 
                                 "GPA欄位": identified_cols.get('GPA')})

                        # 處理原始表格數據，準備 DataFrame
                        
                        # 確保 identified_cols 中的每個識別到的 'Column_X' 都有對應的索引
                        col_mapping = {}
                        for key, col_id in identified_cols.items():
                            if col_id and col_id.startswith('Column_'):
                                try:
                                    # 提取 Column_X 中的數字 X，轉換為 0-based index
                                    original_col_idx = int(col_id.split('_')[1]) - 1
                                    col_mapping[key] = original_col_idx
                                except ValueError:
                                    col_mapping[key] = None
                            else:
                                col_mapping[key] = None

                        # 跳過第一行（標頭行），從第二行開始處理數據
                        for row_idx, row_cells in enumerate(table):
                            if row_idx == 0: # 假設第一行是標頭
                                continue

                            # 確保行足夠長，可以訪問所有映射的列
                            max_idx = -1
                            if col_mapping:
                                max_idx = max(filter(lambda x: x is not None, col_mapping.values()))
                            
                            if not row_cells or len(row_cells) <= max_idx:
                                # st.warning(f"  行 {row_idx+1} (0-indexed: {row_idx}) 因長度不足或為空而跳過。內容: {row_cells}")
                                continue

                            row_data = {}
                            # 使用識別到的欄位名稱和原始索引來構建行數據
                            for identified_key, original_col_idx in col_mapping.items():
                                if original_col_idx is not None and original_col_idx < len(row_cells):
                                    row_data[identified_key] = normalize_text(row_cells[original_col_idx])
                                else:
                                    row_data[identified_key] = "" # 確保欄位存在，即使為空

                            # 僅當科目名稱不為空時才添加該行
                            if row_data.get('科目名稱') and row_data.get('科目名稱').strip():
                                all_extracted_data.append(row_data)

                    else:
                        st.info(f"  頁面 {page_num + 1} 的表格 {table_idx + 1} 未識別為成績表。")
                        # 僅當 table[0] 存在時才顯示內容，避免 IndexError
                        if table and table[0]:
                            st.warning("該行被判斷為空行、標頭行或行政性文字，已跳過。原始資料列內容: " + str([normalize_text(c) for c in table[0]]))
                        else:
                            st.warning("該行被判斷為空行、標頭行或行政性文字，已跳過。原始資料列內容: N/A")


    except Exception as e:
        st.error(f"處理 PDF 檔案時發生錯誤: {e}")
        return pd.DataFrame(), 0.0, 0.0, [], [] # 返回空列表

    # 將所有提取的數據轉換為 DataFrame
    df = pd.DataFrame(all_extracted_data)
    
    # 確保 DataFrame 中存在所有預期的欄位，如果不存在則添加空欄位
    expected_cols = ['學年', '學期', '科目名稱', '學分', 'GPA']
    for col in expected_cols:
        if col not in df.columns:
            df[col] = ''

    if df.empty:
        st.warning("未從 PDF 中提取到任何有效的成績數據。")
        return pd.DataFrame(), 0.0, 0.0, [], [] # 返回空列表

    # 計算總學分數和平均 GPA
    total_credits, average_gpa, calculated_courses, failed_courses = calculate_total_credits(df.copy(), grades_mapping) # 傳遞副本避免修改原始 df

    return df, total_credits, average_gpa, calculated_courses, failed_courses

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
    'F': 0.0, 'X': 0.0, 'XF': 0.0, # X 或 XF 通常代表不及格
    'E': 0.0 # 某些學校可能使用 E 代表不及格
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
        df_grades, total_credits, average_gpa, calculated_courses, failed_courses = process_pdf_file(pdf_bytes, edited_grades_mapping)
    
    if not df_grades.empty:
        st.subheader("提取到的成績數據 (部分預覽)")
        st.dataframe(df_grades)

        st.subheader("計算結果")
        st.metric("總學分數", f"{total_credits:.2f}")
        st.metric("平均 GPA", f"{average_gpa:.2f}")

        # 顯示通過的科目
        if calculated_courses:
            st.subheader("✅ 通過的科目")
            calculated_df = pd.DataFrame(calculated_courses)
            # 選擇要顯示的列
            display_cols = ['學年', '學期', '科目名稱', '學分', 'GPA', '狀態']
            # 過濾掉那些在 DataFrame 中不存在的列
            final_display_cols = [col for col in display_cols if col in calculated_df.columns]
            st.dataframe(calculated_df[final_display_cols], height=300, use_container_width=True)
            st.info("請注意，'抵免' 或 '通過' 的科目學分已計入總學分，但 GPA 不計入平均。")

        # 顯示不及格的科目
        if failed_courses:
            st.subheader("❌ 不及格的科目")
            failed_df = pd.DataFrame(failed_courses)
            # 選擇要顯示的列
            display_failed_cols = ['學年', '學期', '科目名稱', '學分', 'GPA', '狀態']
            # 過濾掉那些在 DataFrame 中不存在的列
            final_display_failed_cols = [col for col in display_failed_cols if col in failed_df.columns]
            st.dataframe(failed_df[final_display_failed_cols], height=200, use_container_width=True)
            st.info("這些科目因成績不及格 ('D', 'E', 'F' 等) 而未計入 GPA 平均。")


        if calculated_courses or failed_courses:
            # 下載通過的科目
            if calculated_courses:
                csv_data_passed = pd.DataFrame(calculated_courses).to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="下載通過的科目列表為 CSV",
                    data=csv_data_passed,
                    file_name=f"{uploaded_file.name.replace('.pdf', '')}_calculated_courses.csv",
                    mime="text/csv",
                    key="download_passed_btn"
                )
            # 下載不及格的科目
            if failed_courses:
                csv_data_failed = pd.DataFrame(failed_courses).to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="下載不及格的科目列表為 CSV",
                    data=csv_data_failed,
                    file_name=f"{uploaded_file.name.replace('.pdf', '')}_failed_courses.csv",
                    mime="text/csv",
                    key="download_failed_btn"
                )
            
    else:
        st.error("未能從上傳的 PDF 檔案中提取到任何有效的成績數據。請檢查檔案格式或嘗試其他檔案。")
        st.info("提示：確保您的 PDF 成績單是文字可選取的，而不是圖片掃描件。")

st.markdown("---")
st.write("如果您遇到任何問題，請檢查原始程式碼或提供更多詳細資訊。")
