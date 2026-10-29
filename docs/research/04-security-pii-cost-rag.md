# Research 04 — PII, prompt injection, red-team, chi phí, RAG tiếng Việt (reader/Haiku, 2026-10-28)

## PII
- Presidio: khung tốt, nhưng **không có recognizer tiếng Việt**. Tự viết `PatternRecognizer`; NLP mặc định là spaCy en (https://microsoft.github.io/presidio/analyzer/adding_recognizers).
- Regex gợi ý (phải test): CCCD `\b\d{12}\b`; SĐT `(\+84|0)(3|5|7|8|9)\d{8}\b`; STK cần từ ngữ cảnh ("STK", "số tài khoản").
- `vipii` (https://pypi.org/project/vipii/): regex + NER cho PII tiếng Việt. underthesea NER (`underthesea[deep]`) để nhận tên người/địa chỉ. GLiNER2-PII chưa rõ có hỗ trợ tiếng Việt.
- Pseudonymization: `<PHONE_1>`, bảng ánh xạ theo request lưu trong bộ nhớ có TTL, không ghi vào cache, unmask sau khi nhận response (thiết kế riêng, không có nguồn).

## Prompt injection
- Spotlighting (https://arxiv.org/abs/2403.14720): ASR giảm từ >50% xuống <2% trên GPT. Rẻ, chạy local.
- Llama Prompt Guard 2 (https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M): 86M đa ngôn ngữ, 512 token; 92.4 ms (86M) / 19.3 ms (22M) trên A100; recall@1%FPR 97.5% (tiếng Anh).
- CaMeL (https://arxiv.org/pdf/2503.18813): tách control flow khỏi dữ liệu, gắn capability cho giá trị; trên AgentDojo đạt 77% tác vụ (so với 84% khi không phòng thủ). Phức tạp → chỉ lấy ý tưởng "policy check khi gọi tool".
- Prompt Shields: dịch vụ cloud của Azure, không chạy local.

## Red-team & khung đánh giá
- OWASP LLM Top 10 2025: LLM01 Prompt Injection, LLM02 Sensitive Info Disclosure, LLM03 Supply Chain, LLM04 Data/Model Poisoning, LLM05 Improper Output Handling, LLM06 Excessive Agency, LLM07 System Prompt Leakage, LLM08 Vector & Embedding Weaknesses, LLM09 Misinformation, LLM10 Unbounded Consumption.
- OWASP Top 10 for Agentic Applications 2026 (ASI01–ASI10, 12/2025): https://genai.owasp.org/resource/2025-12-09/owasp-top-10-for-agentic-applications-for-2026 (cần đọc tên từng mục).
- Công cụ: garak, PyRIT, promptfoo (lõi MIT), AgentDojo (97 tác vụ, https://arxiv.org/abs/2406.13352).

## Chi phí
- Anthropic prompt caching: read 0.1× (Sonnet/Opus 5.5: 0.05×); write 1.25× (5 phút) / 2× (1 giờ). https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching
- Gemini implicit caching: giảm 75% (2.5, Flash ≥1024 token).
- RedisVL SemanticCache: `distance_threshold` mặc định 0.1 (cosine distance) → hiệu chỉnh trên dữ liệu thật.
- **Rò rỉ cache giữa tenant**: CVE-2026-89032 (LiteLLM, một nguồn duy nhất). Đưa tenant + phạm vi quyền vào khóa cache dạng literal; test bằng canary. CacheAttack: arXiv 2601.23088.
- RouteLLM: giảm chi phí ">2× trong một số trường hợp" mà không giảm chất lượng (https://arxiv.org/abs/2406.18665).

## RAG tiếng Việt
- Embedding: bge-m3; `AITeamVN/Vietnamese_Embedding` (bge-m3 fine-tune); reranker ViRanker (arXiv 2509.09131); benchmark VN-MTEB (arXiv 2507.21500).
- pgvector đủ cho quy mô đồ án, và ACL lọc được ngay trong SQL. Qdrant có p99 tốt hơn ở quy mô lớn.
- ACL: `department`/`allowed_roles` trong metadata, lọc phía server từ claims của token. Cache cũng phải tôn trọng ACL.

## Load test
- k6, Locust, Vegeta (đo p99 một endpoint). Mock LLM có độ trễ cố định → overhead = tổng − mock.
