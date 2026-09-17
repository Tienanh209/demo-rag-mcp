# Kịch bản thuyết trình — YZU AI Center Assistant

**Cấu trúc 4 phần:** Giới thiệu → Kiến trúc → Workflow → Lý do chọn công nghệ
**Thời lượng:** 20 phút nói + 5–7 phút Q&A
**Hình vẽ:** `docs/diagrams/architecture.png` (Phần 2) · `docs/diagrams/workflow.png` (Phần 3) — bản `.svg` để chèn vào PowerPoint không vỡ nét khi phóng to.

Phần *"Nói"* là lời thoại có thể đọc gần như nguyên văn. Phần *"Ghi chú"* chỉ mình đọc.

---

## Chuẩn bị trước khi vào phòng

```bash
make run
```

- Chạy trước 10 phút để model embedding load xong — **lệnh đầu tiên luôn chậm, đừng để nó chậm trên sân khấu.**
- Mở sẵn: web console `127.0.0.1:8000` (trace panel bật) + tab `ai.yzu.edu.tw` để đối chiếu citation.
- Có sẵn một session cũ trong sidebar.
- **Toggle ngôn ngữ để ở `EN`** — nếu để `中文` thì câu trả lời sẽ ra tiếng Trung.
- Mạng chết → **không còn phương án offline** (đã gỡ khỏi code, vì với câu hỏi tiếng Anh nó trả về chữ Hán thô không đọc được). Chuẩn bị: **điện thoại phát wifi**, và một **video demo quay sẵn**. Nếu bị hỏi, trả lời thẳng: hệ thống yêu cầu có model, và nó báo lỗi ngay lúc khởi động thay vì chạy nửa vời.

### Bấm giờ

| Phần | Nội dung | Phút |
|---|---|---|
| **1** | Giới thiệu project + demo ngắn | 4:00 |
| **2** | Kiến trúc tổng quan (hình) | 5:00 |
| **3** | Workflow một lượt hỏi đáp (hình) | 5:00 |
| **4** | Lý do lựa chọn công nghệ | 6:00 |
| — | Kết + Q&A | 5:00+ |

> **Nếu bị cắt còn 12 phút:** Phần 1 rút còn 2 phút (demo 3 câu), Phần 2 giữ nguyên, Phần 3 giữ nguyên, Phần 4 chỉ nói nhóm A và B.

---

# PHẦN 1 — Project này làm gì

## 1.1 Mở đầu (45 giây)

**Nói:**

> Chào thầy cô và mọi người. Em là Anh Cao.
>
> Em xây một **chatbot hỏi đáp về Trung tâm AI của Đại học Nguyên Trí** — ICAIA. Người dùng hỏi bằng tiếng Trung hoặc tiếng Anh về học trình TAICA, khóa học, phòng lab, thiết bị, giảng viên, tin tức — hệ thống trả lời **dựa trên chính nội dung website của trung tâm**, và **mọi câu trả lời đều dẫn link về trang gốc**.
>
> Điểm khác biệt về mặt kỹ thuật nằm ở chỗ: phần tri thức không nằm trong chatbot. Nó nằm sau một **MCP server** riêng — và đó là điều em sẽ dành phần lớn thời gian để nói.

## 1.2 Bài toán (45 giây)

**Nói:**

> Vấn đề rất cụ thể. Website trung tâm khi thu thập có **47 trang**, thông tin nằm rải rác: học trình ở một mục, giảng viên ở mục khác, tin tức ở mục thứ ba. Sinh viên muốn biết "học trình thị giác máy tính cần bao nhiêu tín chỉ" phải tự đi tìm.
>
> Nhưng nếu chỉ đưa nội dung đó cho một LLM rồi hỏi, ta gặp đúng hai vấn đề kinh điển:
> **Một — nó bịa.** Hỏi gì cũng có câu trả lời trôi chảy, kể cả khi dữ liệu không có.
> **Hai — không kiểm chứng được.** Người đọc không biết câu trả lời đến từ đâu.
>
> Nên hệ thống này được xây quanh hai ràng buộc: **mọi khẳng định phải truy ngược được về một URL**, và **khi không đủ căn cứ thì từ chối chứ không đoán**.

## 1.3 Demo ngắn (2 phút 30)

**Nói (15 giây dẫn):**

> Em demo nhanh bốn câu, để mọi người thấy hệ thống làm được gì trước khi nghe nó được xây ra sao. Em để **trace panel mở suốt** — mỗi câu hỏi mọi người sẽ thấy hệ thống nghĩ gì ở từng bước.

> Corpus là tiếng Trung, câu hỏi là tiếng Anh — bước viết lại truy vấn sẽ dịch sang thuật ngữ tiếng Trung. Mở trace ra là thấy, và đó cũng là một điểm đáng nói.

**Câu 1 — Hỏi trực tiếp.** Gõ: `What credit programs does TAICA offer?`

> Câu trả lời về kèm citation `[1] [2]`. Em click một link — đây là trang gốc. **Không có câu nào không truy ngược được.** Trong trace, truy vấn đã được viết lại thành `元智大學AI中心學分學程` — câu hỏi tiếng Anh, corpus tiếng Trung, hệ thống tự bắc cầu.

**Câu 2 — Hỏi nối tiếp.** Gõ: `What about the vision technology one?`

> Chú ý: **"the one"** — câu này không có chủ ngữ. Đứng một mình thì retrieve ra rác. Mở trace: truy vấn đã được **viết lại** thành `人工智慧視覺技術學分學程` bằng chủ đề lấy từ memory. Đây là memory đang làm việc thật.

**Câu 3 — Câu mà tìm kiếm từ khóa không làm được.** Gõ: `What's the latest news from the centre?`

> "Tin mới nhất" cần **sắp theo ngày**, không phải theo độ liên quan. Mở trace, bước `tool`: đây là danh sách tool server quảng cáo, đây là tool client chọn — **`get_news`**. **Cùng dạng câu, tool khác nhau** — và quyết định đó nằm chung trong một lần gọi model nhỏ, không tốn thêm request nào.

**Câu 4 — Ngoài phạm vi.** Gõ: `What's the weather like in Hsinchu today?`

> Hệ thống **từ chối** và nói rõ lý do. Em sẽ quay lại chuyện này ở Phần 4 — vì tính năng này từng **bị tắt âm thầm** mà không test nào phát hiện ra.

**Ghi chú demo:**
- Câu 3 là **quan trọng nhất**. Nếu thiếu giờ, cắt câu 1 chứ đừng cắt câu 3.
- Trả lời chậm? Nói luôn: "chậm vì gọi LLM — em có số đo cụ thể ở Phần 3."

---

# PHẦN 2 — Kiến trúc tổng quan

> 🖼 **Chiếu hình `docs/diagrams/architecture.png` và để nguyên suốt phần này.**

## 2.1 Đọc hình từ trên xuống (2 phút 30)

**Nói:**

> Em đi từ trên xuống.
>
> **Tầng trên cùng — HOST.** Web console và CLI terminal. Bên phải, ô nét đứt: **Claude Desktop**. Cả ba đều là "host", và cả ba nói chuyện với cùng một hệ thống bên dưới.
>
> **Tầng thứ hai — MCP CLIENT**, trong `src/client`. Đây là nơi chứa **toàn bộ phần hội thoại**, gồm bốn khối:
>
> - **`intent.py`** — phân loại câu người dùng thành 5 nhãn: `knowledge`, `follow_up`, `chitchat`, `meta`, `out_of_scope`. Luật khớp trước, LLM chỉ được gọi khi luật không chắc.
> - **`router.py`** — mỗi nhãn ánh xạ sang một danh sách subagent có thứ tự.
> - **`planner.py`** — một lần gọi model nhỏ quyết định đồng thời intent, tool và truy vấn tìm kiếm.
> - **`agents/`** — ba subagent: `retrieval` thực thi kế hoạch đó, `answer` sinh câu trả lời và giữ cổng từ chối, `summary` nén hội thoại dài.
> - **`memory.py`** — ba tầng ghi nhớ, mũi tên hai chiều với subagent vì nó vừa được đọc vừa được ghi trong mỗi lượt.
>
> **Tầng giữa — MCP.** Đây là **ranh giới tiến trình**, giao thức JSON-RPC. Server công bố qua đây **cả ba primitive của MCP**: 6 Tools, 2 Resources, 1 Prompt. Đa số implementation chỉ làm Tools.
>
> **Tầng dưới — MCP SERVER**, trong `src/server`. Ba module: `retriever.py` làm tìm kiếm lai, `store.py` là lớp lưu trữ, `ingest.py` dựng index.
>
> **Dưới cùng** là đường dữ liệu: crawl website → `data/raw/` → ingest → chunk trong ChromaDB và BM25. Corpus gồm hai thế hệ: trang hiện hành, và nội dung giữ lại từ trước khi website đổi mới — nhưng trích dẫn của cả hai nhóm đều trỏ thẳng về ai.yzu.edu.tw, không qua bên thứ ba nào: trang nào còn tồn tại thì dẫn đúng trang đó, trang nào đã gỡ thì dẫn về trang chủ hiện hành của trung tâm.

## 2.2 Điểm mấu chốt của kiến trúc (2 phút)

**Nói:**

> Giờ em nói **điều quan trọng nhất trong cả hình này**, và nó nằm ở dòng chữ cam trong ô server:
>
> **"Chỉ làm retrieval. Không memory, không LLM, không trạng thái hội thoại."**
>
> Server **không biết gì về hội thoại**. Nó không biết người dùng là ai, đã hỏi gì trước đó, đang nói về chủ đề nào. Nó chỉ nhận một truy vấn và trả về đoạn văn.
>
> **Và chính vì thế** — mọi người nhìn đường nét đứt bên phải hình — **Claude Desktop cắm thẳng vào MCP server đó và chạy được ngay, bỏ qua hoàn toàn client của em, không sửa một dòng code.**
>
> Nếu em nhét memory hoặc LLM vào server, đường nét đứt đó **biến mất**. Em sẽ có một API HTTP đeo nhãn MCP, chứ không phải một MCP server thật. Ranh giới đó chính là toàn bộ giá trị của MCP trong bài này.

**Ghi chú:** Đây là ý ăn điểm nhất. Chỉ tay vào dòng chữ cam, rồi chỉ vào đường nét đứt. Nói chậm.

## 2.3 Transport (30 giây)

**Nói:**

> Một chi tiết trong dải MCP màu tím: **transport = stdio hoặc HTTP.**
>
> `stdio` là mặc định — client **sinh server ra như một tiến trình con**, đúng cơ chế Claude Desktop dùng. `MCP_TRANSPORT=http` thì server chạy độc lập, có thể ở máy khác.
>
> **Một biến môi trường. Không đổi một dòng code.** Vì transport là quyết định triển khai, không phải quyết định kiến trúc.

---

# PHẦN 3 — Workflow một lượt hỏi đáp

> 🖼 **Chuyển sang hình `docs/diagrams/workflow.png`.**

## 3.1 Dẫn (20 giây)

**Nói:**

> Đây là **một lượt thật**, không phải sơ đồ lý thuyết — các chặng và mốc thời gian em copy nguyên từ trace panel. Câu hỏi là `What's the latest news from the centre?`, đúng câu vừa demo.
>
> Cột trái là client, cột phải là server. Chín chặng.

## 3.2 Chặng 1–4: phía client, chưa chạm server (1 phút 30)

**Nói:**

> **Chặng 1 — intent.** Luật khớp được ngay: câu có vốn từ trong phạm vi → `knowledge`, độ tin cậy 0.80. Chú ý badge xanh bên phải: **~0 mili giây, 0 token.** Không gọi LLM.
>
> **Chặng 2 — router.** Tra bảng: `knowledge` → ba subagent. Nếu là `chitchat` hay `out_of_scope` thì trả lời sẵn và **dừng ở đây** — không đi tìm kiếm gì cả.
>
> **Chặng 3 — tool.** Đọc schema của 4 tool mà server đã gửi lúc MCP discovery, rồi chọn **`get_news`** — vì câu này cần sắp theo **ngày**, không phải theo độ liên quan. Chặng này hiện ~0 ms: nó đã được quyết cùng lúc với intent trong một request duy nhất.
>
> Dòng cam ở dưới: **tên tool được đối chiếu lại với danh sách server thật sự quảng cáo.** LLM bịa tên tool là kiểu hỏng hiển nhiên nhất ở đây, nên nó bị chặn ngay.
>
> **Chặng 4 — retrieval.** Ghép chủ đề và thực thể từ **working memory** vào câu hỏi → ra 2 biến thể truy vấn, bắn song song. **Đây là chặng làm cho câu "那個學程呢？" trả lời được** — câu không có chủ ngữ được giải **trước** khi đi tìm, chứ không phải hy vọng retrieval tự đoán.

## 3.3 Chặng 5–6: vượt ranh giới MCP (1 phút)

**Nói:**

> **Chặng 5** là lúc vượt ranh giới tiến trình. Gọi `get_news(limit=5)` qua JSON-RPC. Bên phải, server chạy: ChromaDB dense top-12 cộng BM25 top-12, RRF sắp xếp, confidence chấm riêng, trả về 5 bản ghi.
>
> **Chặng 6 — deep read, có điều kiện và tối đa một lần.** Nếu đoạn tốt nhất **ngắn dưới 300 ký tự**, hệ thống gọi thêm `get_document` để đọc nguyên trang. Mục đích là **cứu một đoạn bị cắt giữa chừng**, không phải kéo cả trang vào prompt — nên nó bị chặn ở một lần và cắt ở 1500 ký tự.

## 3.4 Chặng 7: cổng từ chối (1 phút 15)

**Nói:**

> **Chặng 7 là chặng em muốn nhấn nhất trong cả hình** — ô đỏ.
>
> Trước khi sinh bất kỳ chữ nào, hệ thống hỏi: **điểm của đoạn tốt nhất có ≥ `MIN_SCORE` = 0.855 không?**
>
> Không → rẽ sang phải, **từ chối và nói rõ lý do. Không gọi LLM. Không đoán.**
>
> Và lý do đặt cổng **ở đây** chứ không phải trong prompt, em viết ngay trong ô: **một model được đưa ngữ cảnh yếu vẫn viết ra một đoạn văn đầy tự tin.** Dặn nó "nếu không biết thì nói không biết" trong prompt là lời khuyên, không phải ràng buộc. Chỗ duy nhất chặn được một cách đáng tin là **chặn trước khi gọi model** — tức là trong luồng điều khiển.

## 3.5 Chặng 8–9 và con số đáng nói nhất (1 phút)

**Nói:**

> **Chặng 8 — answer.** Sinh câu trả lời, mỗi câu khẳng định mang `[n]` ứng với một đoạn cụ thể. Không có LLM thì chuyển sang trích nguyên văn — vẫn có citation.
>
> **Chặng 9 — cập nhật memory rồi lưu đĩa.** Một chi tiết nhỏ nhưng cố ý: **lượt hội thoại được lưu TRƯỚC khi chạy tóm tắt.** Tóm tắt là best-effort — nó không được phép làm mất chính cái lượt đã kích hoạt nó.
>
> Và đây là hai con số ở góc dưới bên phải, em cho là đáng nói nhất của cả bài:
>
> **Cả hai lần gọi MCP cộng lại: 27 mili giây.**
> **99.6% của 7.4 giây là ba lần gọi LLM.**
>
> Nghĩa là **độ trễ nằm ở khâu sinh chữ, không nằm ở khâu tìm kiếm.** Nên nếu em tối ưu, em tối ưu đúng chỗ đó: model nhỏ hơn, streaming, gọi ít lần hơn. Tối ưu retrieval ở đây là tối ưu 0.4% — và đó là cách lãng phí thời gian có hệ thống.

**Ghi chú:** Dừng một nhịp sau "27 mili giây". Đây là con số làm khán giả ngồi thẳng lên.

---

# PHẦN 4 — Lý do lựa chọn công nghệ

## 4.0 Dẫn (15 giây)

**Nói:**

> Phần cuối, em đi vào **tại sao chọn từng thứ**. Em nhóm thành bốn nhóm, và với mỗi lựa chọn em nói cả **phương án thay thế đã cân nhắc** — vì một lựa chọn không có phương án thay thế thì không phải lựa chọn.

## 4.1 Nhóm A — Tại sao MCP (1 phút 30)

**Nói:**

> **A1. MCP thay vì gọi hàm trực tiếp hoặc REST API.**
> Phương án rẻ nhất là để client `import` thẳng module retriever. Chạy được ngay, ít code hơn. Nhưng khi đó **chỉ client của em dùng được nó.** Với MCP, server tự mô tả năng lực của nó bằng schema chuẩn, nên **bất kỳ host nào cũng khám phá và dùng được** — Claude Desktop là bằng chứng em demo được tại chỗ. Đây không phải chọn công nghệ cho đẹp, nó là chọn **ranh giới**.
>
> **A2. Server không giữ trạng thái hội thoại.**
> Rất dễ nhét memory vào server cho tiện — client mỏng đi. Nhưng lúc đó server **gắn chặt vào một client duy nhất**. Em đẩy toàn bộ hội thoại lên client để server giữ được tính chất "ai cắm vào cũng chạy".
>
> **A3. Công bố cả ba primitive, không chỉ Tools.**
> Đa số implementation dừng ở Tools. Em thêm **Resources** (`yzu://doc/{url}` — host đọc thẳng trang nguồn) và **Prompt** (`grounded_answer` — template ưu tiên citation mà **server ship kèm dữ liệu của nó**). Lý do: một host khác không biết cách hỏi dữ liệu này cho đúng; **server là bên biết rõ nhất, nên nó nên cung cấp luôn cách hỏi.**

## 4.2 Nhóm B — Tại sao retrieval như vậy (2 phút)

**Nói:**

> **B1. Lai dense + BM25, thay vì chỉ dùng vector.**
> Dense bắt được diễn đạt khác nhau; BM25 bắt được **tên riêng chính xác** — mã học trình, tên chương trình. **Dùng riêng cái nào cũng hỏng một lớp câu hỏi.** Corpus này đầy danh từ riêng tiếng Trung, nên bỏ BM25 là bỏ đúng lớp câu hỏi sinh viên hay hỏi nhất.
>
> **B2. RRF để gộp, thay vì chuẩn hóa rồi cộng có trọng số.**
> Cosine nằm trong khoảng 0–1, BM25 thì không chặn trên. Muốn cộng lại phải chuẩn hóa, mà chuẩn hóa thì phải chọn thang — và mỗi lần corpus đổi là thang đổi. **RRF gộp theo thứ hạng, nên nó né toàn bộ chuyện chuẩn hóa.**
>
> **B3. Nhưng confidence phải chấm RIÊNG — đây là bài học đắt nhất.**
> RRF là bộ **gộp thứ hạng**, không phải điểm liên quan: kết quả đứng đầu luôn được `1/(k+1)` **bất kể nó tệ đến đâu**. Em từng dùng chính nó làm confidence, nên câu "hôm nay thời tiết thế nào" và câu "TAICA có học trình gì" **đều trả về 1.0000** — cổng từ chối không thể phân biệt. Giờ confidence tính riêng: `max(cosine, độ phủ từ khóa của câu hỏi)`. **RRF lo thứ tự, confidence lo có nên trả lời hay không. Hai câu hỏi khác nhau thì phải hai hàm khác nhau.**
>
> **B4. ChromaDB, và em chọn nó vì lý do có thể mọi người không đoán.**
> Ở quy mô 373 chunk, **một phép nhân ma trận numpy cũng chạy được** — em không cần ANN. Em chọn Chroma vì **bề mặt truy vấn metadata**: `get_news` cần lọc theo ngày, và mỗi chunk còn mang `status` + `cite_url` để phân biệt nguồn hiện hành với nguồn lưu trữ. Chroma cho em cái đó cộng tính bền vững **mà không phải chạy thêm service nào**. Nếu chọn FAISS, em được tốc độ không cần và mất đúng thứ em cần.
>
> **B5. jieba cộng bigram ký tự.**
> jieba cắt `學分學程可以抵免` và `各學分學程間可互相抵免` **khác nhau**, nên index chỉ theo từ sẽ trượt cái trùng khớp mà người đọc nhận ra ngay. Bigram ký tự là lớp dự phòng **độc lập với cách cắt từ** — thực hành chuẩn trong IR tiếng Trung.
>
> **B6. Chunk 500 ký tự, chồng lấn 80, cắt theo heading trước.**
> Và quan trọng: **mỗi chunk mang theo "Tiêu đề > Heading" ở đầu.** Một mảnh văn bản về một mình là `本聯盟各學分學程總修習學分為 15 學分` — không rõ nói về cái gì. Có tiền tố `TAICA聯盟學分學程介紹 > 人工智慧視覺技術學分學程` thì rõ ngay. **Chunk phải tự mang được ngữ cảnh của chính nó**, vì lúc đưa vào prompt nó không còn hàng xóm.

## 4.3 Nhóm C — Tại sao client được xây như vậy (1 phút 15)

**Nói:**

> **C1. Luật chạy trước, LLM chỉ khi luật không chắc.**
> Phương án dễ là gọi LLM cho mọi câu. Ba lý do em không làm: **độ trễ** — mỗi lần gọi là ~2 giây; **chi phí**; và quan trọng nhất, **luật là thứ giữ hệ thống chạy được khi không có model nào.** Em muốn "không có API key" là một **cấu hình hợp lệ**, không phải trạng thái hỏng.
>
> **C2. Router là bảng tra, không phải chuỗi if-else, cũng không phải agent tự do.**
> Có thể để LLM tự quyết định gọi gì — linh hoạt hơn, nhưng **không tái lập được và không giải thích được**. Bảng tra thì thêm năng lực = thêm một dòng, và quyết định định tuyến **hiện ra trong trace** — đúng cái mọi người vừa thấy khi em mở trace panel.
>
> **C3. Bốn subagent riêng, thay vì một prompt to.**
> Nhét viết-lại-truy-vấn, chọn-tool và sinh-câu-trả-lời vào một prompt thì chạy được, nhưng **khi sai thì không biết sai ở đâu**. Tách ra thì mỗi chặng có tên riêng trong trace, có fallback riêng, và **cổng từ chối nằm ở một chỗ xác định** thay vì trộn vào chỉ dẫn.
>
> **C4. Memory ba tầng, không phải một khối.**
> Ba tầng có **vòng đời khác nhau và chi phí token khác nhau**: 6 lượt gần nhất nguyên văn / chủ đề + ≤12 thực thể / tóm tắt cuộn mỗi 8 lượt. Gộp làm một là lỗi thường gặp — **hoặc quên quá nhanh, hoặc làm tràn context window.**

## 4.4 Nhóm D — Tại sao xuống cấp có kiểm soát (1 phút)

**Nói:**

> **D1. Từ chối nằm trong luồng điều khiển, không nằm trong prompt.** Em vừa giải thích ở Phần 3 — đây là lựa chọn kiến trúc, không phải chi tiết cài đặt.
>
> **D2. Ngưỡng từ chối được HIỆU CHỈNH, không phải đoán.**
> Em chấm 27 câu có nhãn — 19 câu trả lời được (12 tiếng Trung, 7 tiếng Anh) và 8 câu ngoài phạm vi — **qua đúng bước viết lại truy vấn mà client thật sự chạy**, rồi lấy chỗ hai phân bố tách nhau: câu trả lời được thấp nhất **0.8619**, câu ngoài phạm vi cao nhất **0.8489**, ngưỡng **0.855**. Corpus đổi thì ngưỡng đổi — đó là lý do phải chạy lại `make calibrate` sau mỗi lần ingest.
>
> Chi tiết đáng nói: nếu chấm **câu hỏi thô** thay vì câu đã viết lại, mọi câu tiếng Anh đều rơi vào 0.77–0.84 bất kể có liên quan hay không — **không ngưỡng nào tách được**. Đo sai pipeline thì ra sai kết luận.
>
> Và đây là phần em muốn nói thẳng: **ngưỡng này từng là 0.35, trong khi mọi câu hỏi đều chấm trên 0.83** — kể cả `推薦一部電影`. Tức là **cổng từ chối là code sống nhưng không bao giờ có thể kích hoạt.** Không unit test nào bắt được, vì nó không phải lỗi logic — nó là lỗi **con số**. Chỉ có hiệu chỉnh mới lôi ra.
>
> Biên an toàn là **0.023** — sạch nhưng mỏng. Nguyên nhân ở model embedding chứ không ở corpus: `e5-small` chấm hai đoạn text **không liên quan gì nhau** cũng tầm 0.75–0.85, nên dải dùng được rất hẹp. Cách sửa đúng là chấm so với **nền tương đồng của chính corpus** thay vì cosine thô — em biết phải làm gì, và em chưa làm.
>
> **D3. LLM gọi qua giao diện OpenAI-compatible, không dùng SDK riêng của hãng nào.**
> Nên đổi từ GPT sang Gemini hay sang **Ollama chạy local** chỉ là đổi `LLM_BASE_URL` và `LLM_MODEL`. Không khóa vào một nhà cung cấp.
>
> **D4. Hỏng thì báo thẳng, và xuống bậc trong phạm vi một lượt.**
> Hệ thống **bắt buộc có model**: thiếu key thì nó thoát ngay lúc khởi động kèm thông báo rõ ràng, chứ không chạy lên rồi từ chối mọi câu hỏi — vì như vậy nhìn giống index hỏng hơn là thiếu key. Trước đây em có đường offline trả lời bằng trích nguyên văn; **em đã gỡ**, vì với câu hỏi tiếng Anh trên corpus tiếng Trung nó trả về chữ Hán thô, tức là giả vờ còn chạy trong khi thực chất đã hỏng.
>
> Còn trong một lượt thì vẫn xuống bậc: viết lại truy vấn hỏng → rơi về đường tất định có **bảng ánh xạ Anh–Trung** (em đo được 0.88, vẫn qua ngưỡng); sinh chữ hỏng → trả về nguồn kèm lời giải thích; tóm tắt hỏng → không bao giờ mất lượt vừa trả lời. Không có model embedding → lùi về BM25 thuần và **badge ghi "lexical"**. Nguyên tắc không đổi: **hệ thống không bao giờ giả vờ mạnh hơn thực tế.**

## 4.5 Số đo và giới hạn (1 phút)

**Nói:**

> Cuối cùng, con số. Bộ đánh giá 15 câu: **doc hit@5 = 0.933, MRR = 0.813, answer_span@5 = 0.667, retrieval p50 = 70 mili giây.**
>
> `answer_span` là chỉ số **đáng tin nhất** trong bốn cái: nó kiểm tra đoạn lấy về **có thật sự chứa dữ kiện cần tìm** hay không. Một hệ thống có thể đạt hit@5 tuyệt đối trong khi chỉ trả về **menu điều hướng** của trang. Đó là lý do em báo cáo nó riêng, và **báo cáo con số thấp nhất chứ không phải con số đẹp nhất.**
>
> Vì sao 0.667: **3 trong 5 ca trượt là lỗi Unicode, không phải lỗi retrieval.** Site dùng ký tự tương thích — 領 U+F9B4 — trông **giống hệt** cái người dùng gõ, 領 U+9818. Dữ kiện có trong index; khớp từ khóa không nhìn thấy nó.
>
> Giới hạn em biết và chưa sửa:
> - Biên từ chối 0.023 — mỏng.
> - Câu hỏi tiếng Anh phụ thuộc vào bước viết lại truy vấn; nếu lần gọi đó hỏng thì chỉ còn bảng ánh xạ ~20 thuật ngữ đỡ.
> - 3 ca trượt do ký tự Unicode nhìn giống nhau → chuẩn hóa ở cả ingest và truy vấn.
> - Một trang chiếm 46% corpus (danh mục công bố của một giáo sư) → cần giới hạn tỉ trọng mỗi tài liệu.
> - Index là **ảnh chụp tại một thời điểm**, chưa có cập nhật tăng dần.
> - Chưa có xác thực trên web client — đây là bản triển khai phòng lab.
> - Đánh giá mới phủ retrieval; **độ trung thực của câu sinh ra vẫn chấm tay** — RAGAS là bước kế tiếp.

**Ghi chú:** Nói phần giới hạn bình thản, không xin lỗi. Biết giới hạn hệ thống mình là năng lực.

---

# KẾT (30 giây)

**Nói:**

> Tóm lại ba điều:
>
> **Một — tri thức nằm sau một MCP server thật.** Server không biết gì về hội thoại, nên host nào cắm vào cũng chạy, kể cả Claude Desktop.
> **Hai — mọi câu trả lời trích nguồn**, và khi không đủ căn cứ thì nó **từ chối trong luồng điều khiển**, trước khi model kịp viết ra thứ gì.
> **Ba — mọi con số trong bài là đo thật**, kể cả con số không đẹp.
>
> Chạy thử: `make install`, `make ingest`, `make run`. Spec đầy đủ ở `docs/functional-spec.md`, ghi chú thiết kế ở `README.md`.
>
> Em xin cảm ơn. Mời thầy cô đặt câu hỏi.

---

# CHUẨN BỊ Q&A

**"Sao không dùng LangChain / LlamaIndex?"**
> Hai thứ quan trọng nhất của bài này — **ranh giới MCP** và **cổng từ chối** — là thứ em cần nhìn thấy và kiểm soát ở mức luồng điều khiển. Cả ba con bug khó nhất em gặp đều nằm ở lớp mà framework thường giấu đi. Ở quy mô 373 chunk, chi phí tự viết thấp hơn chi phí không nhìn thấy gì.

**"Vì sao không dùng embedding của OpenAI cho chính xác hơn?"**
> Vì như vậy **mỗi lần ingest lại toàn bộ corpus đều phải gọi mạng và trả tiền**, và index sẽ khóa vào một nhà cung cấp. `multilingual-e5-small` chạy local, miễn phí, hỗ trợ đa ngôn ngữ Trung–Anh. Cái giá phải trả là **ngưỡng tương đồng cao** — chính là biên 0.023 mỏng mà em vừa nói. Đó là một đánh đổi em biết mình đang chọn.

**"Reranker sao lại tắt?"**
> Code có sẵn, bật bằng một biến. Em tắt vì cross-encoder `bge-reranker-v2-m3` nặng hơn nhiều so với lợi ích đo được trên corpus 373 chunk — nó phá đúng cái phần **27 mili giây** đang tốt. Nếu corpus lên vài nghìn chunk thì đó là thứ em bật đầu tiên.

**"Hệ thống có thể bịa không?"**
> Hai lớp chặn. Lớp một là **cổng confidence** — chặn trước khi gọi model, vì prompt không đủ tin cậy để chặn. Lớp hai là **citation `[n]` gắn về URL**, nên mọi khẳng định kiểm chứng được bằng tay. Cái em chưa có là chấm **tự động** độ trung thực của câu sinh ra.

**"Mở rộng lên bao nhiêu dữ liệu được?"**
> Hiện tại đơn tiến trình, index trong bộ nhớ — ổn tới vài nghìn chunk. Vượt qua đó thì phần cần đổi là **store**, không phải phần MCP hay client. Đó chính là lợi ích của việc server không giữ trạng thái hội thoại.

**"Vì sao chọn stdio làm mặc định?"**
> Vì đó là cơ chế **Claude Desktop dùng**, nên mặc định stdio làm cho phần demo "cắm vào host khác" chạy được ngay mà không phải cấu hình gì. HTTP dành cho triển khai tách máy — và đổi giữa hai cái là một biến môi trường.

**"Có bao nhiêu phần là code bạn tự viết?"**
> Toàn bộ, trừ hai file em ghi rõ trong README: `scripts/smoke_server.py` và `scripts/calibrate.py` được em đọc lại từng dòng nhưng không viết trong lượt chính. Em ghi điều đó trong repo chứ không để ai phải hỏi.

---

# CHECKLIST PHÚT CHÓT

- [ ] `make run` đã chạy, model embedding load xong
- [ ] `make smoke` pass
- [ ] Trace panel đang mở
- [ ] Có sẵn 1 session cũ trong sidebar
- [ ] Tab `ai.yzu.edu.tw` mở sẵn để đối chiếu citation
- [ ] **Toggle ngôn ngữ đang ở `EN`**
- [ ] Điện thoại phát wifi sẵn + video demo dự phòng (không còn chế độ offline)
- [ ] Hai hình `docs/diagrams/*.png` đã chèn vào slide
- [ ] Claude Desktop đã cấu hình (`make stdio-config`) nếu còn thời gian demo
