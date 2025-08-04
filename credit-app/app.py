import streamlit as st
import pandas as pd
import io
import pdfplumber

# ... (parse_gpa_to_numeric 和 analyze_student_grades 函數不變) ...

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
                    # 嘗試從每個頁面提取表格
                    # 這裡我們嘗試更精確地定義表格的邊界和設定
                    # 根據您提供的 PDF 內容（邱旭廷成績總表.pdf），表格的頂部和底部，以及列寬相對固定。
                    # 您可以嘗試使用 'explicit_vertical_lines' 和 'explicit_horizontal_lines'
                    # 或者調整 'table_settings' 參數來微調提取。
                    # 這裡先嘗試調整 'vertical_strategy' 和 'horizontal_strategy' 為 'text'
                    # 這通常對沒有明確線條的表格有效，但也可能影響線條清晰的表格。
                    # 針對您的 PDF，表格線條較清晰，'lattice' 模式可能更合適，但如果出現nan，
                    # 可能是文字不在格子中間導致。可以嘗試以下設置或嘗試手動定義表格區域。
                    
                    table_settings = {
                        "vertical_strategy": "lines",  # 優先使用垂直線
                        "horizontal_strategy": "lines", # 優先使用水平線
                        "snap_tolerance": 3,  # 增加對齊容忍度
                        "snap_vertical": [50, 100, 150, 350, 400, 450], # 這些值需要根據實際PDF的列位置調整
                        "snap_horizontal": page.find_lines(), # 自動找到水平線
                        "min_words_horizontal": 1 # 一行至少包含一個詞
                    }
                    
                    # 嘗試指定表格區域，如果表格在頁面中的位置固定
                    # 根據您提供的PDF，成績表格大約從頁面中間開始
                    # 您可能需要用 pdfplumber 的 debug 模式或手工測量來找到確切的坐標
                    # 這裡我根據之前的 PDF 內容大概估計了一個區域，這可能需要微調
                    # area = [top_x, top_y, bottom_x, bottom_y] in points (72 points = 1 inch)
                    # For example, if the table starts roughly 2 inches from top and is 6 inches wide
                    # area = [144, 0, 800, 600] # 這是一個粗略的估計，請根據實際PDF調整
                    
                    # tables = page.extract_tables(table_settings) # 帶入設定

                    # 因為您原始的 PDF 中，科目名稱有換行符，pdfplumber 在提取時可能會將其視為多行，
                    # 或在不同的框中。直接提取文字再重組可能是更穩健的方案。
                    # 或者，我們可以讓 pdfplumber 提取 cells，然後手動組合。

                    # 最直接的方法是，先不管 pdfplumber 的表格提取，直接提取所有文字，
                    # 然後用正規表達式或更精細的字串處理來匹配模式。
                    # 但這會讓程式碼變得複雜。

                    # 讓我們回到 extract_tables()，並改進清理過程：
                    tables = page.extract_tables() # 保持預設提取，但加強後處理

                    for table in tables:
                        if not table:
                            continue

                        # 清理表頭，並確保長度符合預期
                        header = [col.replace('\n', ' ').strip() for col in table[0] if col is not None]
                        # 檢查 header 是否包含預期的關鍵字
                        if "學年度" in header and "科目名稱" in header and "學分" in header and "GPA" in header:
                            # 建立一個映射，將提取到的列名映射到標準列名
                            col_mapping = {}
                            for i, h in enumerate(header):
                                if "學年度" in h: col_mapping[h] = "學年度"
                                elif "學期" in h: col_mapping[h] = "學期"
                                elif "選課代號" in h: col_mapping[h] = "選課代號"
                                elif "科目名稱" in h: col_mapping[h] = "科目名稱"
                                elif "學分" in h: col_mapping[h] = "學分"
                                elif "GPA" in h: col_mapping[h] = "GPA"
                                # 處理其他可能存在的列名（例如，由於pdfplumber分割導致的）
                                else: col_mapping[h] = f"Unknown_Col_{i}" # 防止 Key Error

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
                                df_table[col] = df_table[col].astype(str).str.strip().str.replace('\n', ' ', regex=False).replace('None', pd.NA)
                            
                            all_grades_data.append(df_table)
                
            if not all_grades_data:
                st.warning("未能從 PDF 中提取任何表格。請檢查 PDF 格式或嘗試調整解析參數。")
                return

            full_grades_df = pd.concat(all_grades_data, ignore_index=True)

            # 數據清洗 (針對內容數據)
            full_grades_df.dropna(how='all', inplace=True) # 移除所有列都是 NaN 的行

            # 確保 '學年度' 是數字且篩選非成績行
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
                st.warning("未能從 PDF 中提取有效的成績數據。請檢查 PDF 格式或嘗試調整解析參數。")

        except Exception as e:
            st.error(f"處理 PDF 檔案時發生錯誤：{e}")
            st.info("請確認您的 PDF 格式是否為清晰的表格。若問題持續，可能是 PDF 結構較為複雜，需要調整 `pdfplumber` 的表格提取設定。")
            st.exception(e)

if __name__ == "__main__":
    main()
