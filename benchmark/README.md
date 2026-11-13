# Benchmark — Day 06

- File: `questions.jsonl` (20 câu: 15 dev q01–q15, 5 test q16–q20). Ngôn ngữ câu hỏi: tiếng Anh 
- Nguồn duy nhất: `pof-ch1-3` (xem `data/manifest.csv`). `gold_page` = số trang PDF vật lý.
- Loại câu (`type`): direct, paraphrase (diễn đạt khác từ trong nguồn), condition (điều kiện/ngoại lệ), filter.

## Chia dev/test 
- Test chỉ lấy từ các section **1.6, 2.5, 3.3** (mỗi chương một section); dev lấy từ các section còn lại. Kiểm tra tự động trong `starter/scripts/validate_benchmark.py` (`TEST_SECTIONS`).
- Rủi ro rò rỉ: trang Summary (p40, p72) và Key Terms (p41–43, p73–75) tóm tắt lại nội dung mọi section, kể cả section test. Ví dụ q16 có bằng chứng thay thế ở Key Terms p41. Các trang này được ghi trong `gold_page`/`alt_evidence` để không chấm sai oan.

## Evidence
- `evidence_quote` nằm trên trang `gold_page[0]`; `alt_evidence` ghi các trang hợp lệ khác. Chấp nhận bất kỳ trang/quote nào trong số đó.
- Quote được copy từ text đã chuẩn hóa (`scripts/dump_pages.py`), nên giữ nguyên lỗi tách chữ của pypdf (ví dụ "t he firm"). So khớp bằng `compact()` (gộp mọi khoảng trắng).
- Kiểm chứng: `python scripts/validate_benchmark.py` → OK (20/20 quote có trên trang gold). Ngoài ra tác giả đã đọc lại thủ công để xác nhận evidence đủ để trả lời.

## Metadata filter
- Trường lọc: `chapter` ("1"/"2"/"3", kiểu string), lấy từ dòng đầu trang dạng `X.Y.Z https://biz.libretexts.org/...`.
- Câu filter: q04 (ch1), q11 (ch2) thuộc dev; q18 (ch3) thuộc test. Filter là **input giả định người dùng cung cấp trước khi truy xuất** (chọn chương). Không dùng gold page/section làm filter.
- Câu được chọn có khái niệm xuất hiện ở nhiều chương (inflation: ch1 và ch3; shareholder: ch1 và ch2). Câu không có filter: cấu hình C chạy không lọc.

## Tiêu chí chọn chiến lược (chốt trước khi xem test)
Chọn trên **dev**: Evidence Hit@3 cao nhất → hòa thì Hit@1 → coherence trung bình → ít chunk / thời gian ingest thấp hơn. Test chỉ chạy một lần sau khi cố định cấu hình.


