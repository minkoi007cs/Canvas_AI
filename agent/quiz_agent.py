"""
Quiz agent: chụp collage ảnh ở zoom cao, download ảnh gốc,
crop từng ô, gửi GPT-4o Vision từng ảnh riêng để nhận diện.
"""
import base64
import re
import time
import json
import requests
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from config import CANVAS_BASE_URL, OPENAI_API_KEY, BASE_DIR

console = Console()
_DEFAULT_SCREENSHOTS = BASE_DIR / "screenshots"
_DEFAULT_SCREENSHOTS.mkdir(exist_ok=True)


def _screenshots_dir():
    from config import get_user_screenshots_dir
    try:
        return get_user_screenshots_dir()
    except Exception:
        return _DEFAULT_SCREENSHOTS


# ─── Entry point ────────────────────────────────────────────────────────────

def solve_quiz(course_id: int, quiz_id: int, assignment_id: int,
               cookies: list, headless: bool = False):
    quiz_url = f"{CANVAS_BASE_URL}/courses/{course_id}/quizzes/{quiz_id}"
    console.print(f"[blue]Mở quiz...[/blue]")

    session_cookies = {c["name"]: c["value"] for c in cookies
                       if "instructure" in c.get("domain", "")}

    with sync_playwright() as p:
        # device_scale_factor=2 → ảnh sắc nét gấp đôi
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            device_scale_factor=2,
        )
        valid = [{**c, "sameSite": "Lax"} if c.get("sameSite") not in ("Strict","Lax","None") else c
                 for c in cookies]
        context.add_cookies(valid)

        page = context.new_page()
        page.goto(quiz_url, wait_until="networkidle", timeout=20000)
        _start_quiz(page)

        # Debug: chụp ảnh xem đang ở trang nào
        dbg =   _screenshots_dir() / "debug_after_start.png"
        page.screenshot(path=str(dbg), full_page=False)
        console.print(f"  [dim]URL sau start: {page.url}[/dim]")

        page_num = 0
        while True:
            page_num += 1
            try:
                page.wait_for_selector(".question", timeout=12000)
            except PlaywrightTimeout:
                # Thử click Resume một lần nữa nếu có
                for sel in ["a:has-text('Resume Quiz')", "a:has-text('Resume quiz')",
                            "button:has-text('Resume')", "#resume_quiz_link"]:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=1000):
                            console.print(f"  [yellow]Retry click: {btn.text_content().strip()}[/yellow]")
                            btn.click()
                            page.wait_for_load_state("networkidle", timeout=10000)
                            break
                    except Exception:
                        continue
                # Thử lại lần nữa
                try:
                    page.wait_for_selector(".question", timeout=8000)
                except PlaywrightTimeout:
                    dbg2 =   _screenshots_dir() / f"debug_no_questions_p{page_num}.png"
                    page.screenshot(path=str(dbg2), full_page=False)
                    console.print(f"  [red]Không tìm thấy .question — xem: {dbg2.name}[/red]")
                    break

            # Scroll để lazy-load ảnh
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.5)

            # Lấy dữ liệu câu hỏi từ DOM
            quiz_data = _extract_quiz_data(page)

            # Với mỗi câu hỏi: lấy ảnh + options → AI trả lời
            q_elements = page.locator(".question").all()
            for qi, qdata in enumerate(quiz_data):
                console.print(f"\n[bold]--- Câu {qi+1} ---[/bold]")

                # 1. Download ảnh gốc (full resolution từ server)
                orig_images = _download_images(qdata.get("image_srcs", []), session_cookies, quiz_id, page_num, qi)

                # 2. Screenshot toàn bộ câu hỏi (collage + labels)
                q_screenshot = None
                if qi < len(q_elements):
                    p2 =   _screenshots_dir() / f"q{page_num}_{qi+1}_element.png"
                    try:
                        q_elements[qi].screenshot(path=str(p2))
                        q_screenshot = str(p2)
                    except Exception:
                        pass

                # 3. Mở dropdown và chụp ảnh để AI thấy options trực quan
                dropdown_screenshots = []
                if qi < len(q_elements):
                    dropdown_screenshots = _capture_dropdown_screenshots(
                        page, q_elements[qi], quiz_id, page_num, qi
                    )

                options = qdata.get("options", [])
                items = qdata.get("items", [])
                q_text = qdata.get("text", "")

                console.print(f"  Options ({len(options)}): {', '.join(options)}")
                console.print(f"  Ảnh gốc: {len(orig_images)} | Element: {'✓' if q_screenshot else '✗'} | Dropdowns: {len(dropdown_screenshots)}")

                # 4. Gửi AI
                answer = _vision_answer(
                    q_text=q_text,
                    items=items,
                    options=options,
                    orig_images=orig_images,
                    q_screenshot=q_screenshot,
                    dropdown_screenshots=dropdown_screenshots,
                    q_index=qi + 1,
                )
                console.print(Panel(
                    Markdown(answer),
                    title=f"[bold green]Câu {qi+1} — Đáp án AI[/bold green]",
                    border_style="green",
                    padding=(1, 2),
                ))

            # Next page?
            moved = False
            for sel in ["button:has-text('Next')", "a:has-text('Next')", "#next-button"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=1000):
                        btn.click()
                        page.wait_for_load_state("networkidle", timeout=8000)
                        moved = True
                        break
                except Exception:
                    continue
            if not moved:
                break

        browser.close()

    console.print(f"\n[bold yellow]→ Điền đáp án vào Canvas:[/bold yellow] {quiz_url}")


# ─── DOM extraction ──────────────────────────────────────────────────────────

def _extract_quiz_data(page) -> list:
    return page.evaluate("""
        () => {
            const questions = document.querySelectorAll('.question');
            const result = [];
            questions.forEach((q) => {
                const obj = { text: '', image_srcs: [], items: [], options: [] };

                const textEl = q.querySelector('.question_text');
                if (textEl) obj.text = textEl.innerText.trim();

                // Tất cả ảnh trong câu (kể cả trong collage)
                q.querySelectorAll('img').forEach(img => {
                    const src = img.src || img.getAttribute('data-src') || '';
                    if (src && !src.startsWith('data:')) obj.image_srcs.push(src);
                });

                // Left-side items (label cần match)
                q.querySelectorAll('.answer_match_left').forEach(el => {
                    obj.items.push(el.innerText.trim());
                });

                // Options từ select (matching) hoặc radio/checkbox (multiple choice)
                const sel = q.querySelector('select');
                if (sel) {
                    Array.from(sel.options).forEach(o => {
                        if (o.value) obj.options.push(o.text.trim());
                    });
                } else {
                    // Radio/checkbox answers
                    q.querySelectorAll('.answer_label, .answer_text, label.answer').forEach(el => {
                        const txt = el.innerText.trim();
                        if (txt) obj.options.push(txt);
                    });
                    // Fallback: try .answer divs
                    if (!obj.options.length) {
                        q.querySelectorAll('.answer').forEach(el => {
                            const txt = el.innerText.trim();
                            if (txt && txt.length < 300) obj.options.push(txt);
                        });
                    }
                }

                result.push(obj);
            });
            return result;
        }
    """)


# ─── Dropdown screenshots ───────────────────────────────────────────────────

def _capture_dropdown_screenshots(page, q_element, quiz_id, page_num, qi) -> list:
    """
    Click mở từng dropdown, chụp ảnh toàn câu hỏi (collage + dropdown mở),
    rồi đóng lại. AI sẽ thấy chính xác options nào có sẵn.
    """
    screenshots = []
    selects = q_element.locator("select").all()

    # Chỉ cần mở 1-2 dropdown đầu là đủ (tất cả cùng options)
    for i, sel_el in enumerate(selects[:2]):
        try:
            # Scroll tới dropdown
            sel_el.scroll_into_view_if_needed()
            time.sleep(0.3)

            # Click để mở
            sel_el.click()
            time.sleep(0.8)  # chờ dropdown render

            # Chụp toàn bộ câu hỏi (thấy cả collage lẫn dropdown đang mở)
            spath =   _screenshots_dir() / f"dropdown_{quiz_id}_p{page_num}_q{qi+1}_s{i+1}.png"
            q_element.screenshot(path=str(spath))
            screenshots.append(str(spath))
            console.print(f"  → Chụp dropdown {i+1} mở: {spath.name}")

            # Đóng dropdown bằng Escape
            page.keyboard.press("Escape")
            time.sleep(0.3)

        except Exception as e:
            console.print(f"  [dim]Dropdown {i+1}: {e}[/dim]")

    return screenshots


# ─── Image downloading ───────────────────────────────────────────────────────

def _download_images(srcs: list, session_cookies: dict, quiz_id, page_num, qi) -> list:
    """Download ảnh gốc từ Canvas server (full resolution)."""
    paths = []
    for ii, src in enumerate(srcs):
        try:
            r = requests.get(src, cookies=session_cookies, timeout=15,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.ok and len(r.content) > 1000:
                ctype = r.headers.get("content-type", "")
                ext = "png" if "png" in ctype else "jpg"
                dest =   _screenshots_dir() / f"orig_{quiz_id}_p{page_num}_q{qi+1}_i{ii+1}.{ext}"
                dest.write_bytes(r.content)
                paths.append(str(dest))
        except Exception as e:
            console.print(f"  [dim]Download ảnh {ii+1}: {e}[/dim]")
    return paths


# ─── AI Vision ───────────────────────────────────────────────────────────────

def _img_b64(path: str):
    ext = Path(path).suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    data = base64.b64encode(Path(path).read_bytes()).decode()
    return mime, data


def _build_image_content(image_paths: list) -> list:
    content = []
    for path in image_paths:
        if path and Path(path).exists():
            mime, data = _img_b64(path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{data}", "detail": "high"},
            })
    return content


def _vision_answer(q_text, items, options, orig_images, q_screenshot,
                   dropdown_screenshots=None, q_index=1) -> str:
    if not OPENAI_API_KEY:
        return "Thiếu OPENAI_API_KEY"

    # Ảnh chính: ảnh gốc download + screenshot element
    main_images = list(orig_images or [])
    if q_screenshot:
        main_images.append(q_screenshot)

    # Ảnh dropdown: chụp khi đang mở (thấy options list trực quan)
    dropdown_imgs = list(dropdown_screenshots or [])

    if not main_images and not dropdown_imgs:
        return "Không có ảnh để phân tích"

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        sys_prompt = (
            "You are an expert in ancient Greek and Roman art, history, and culture. "
            "You identify artworks from visual clues: clothing, posture, objects, setting, artistic style.\n\n"
            "VISUAL IDENTIFICATION GUIDE for 'Women's Lives' quiz (Kent State CLAS-21404):\n"
            "- maenad: wild/frenzied woman, Dionysian scene, thyrsus (fennel staff), animal skin, ecstatic pose\n"
            "- Spartan runner: athletic female in short tunic, running or standing athletic pose, kore-type statue\n"
            "- mourner: funerary scene, woman wailing/gesturing grief, near stele/grave, tearing hair\n"
            "- woman spinning: holding distaff + drop-spindle, or seated at upright loom with loom weights\n"
            "- bride with the groom: wedding scene, veiled woman, chariot/cart procession, torch, groom present\n"
            "- slaves working: multiple figures doing domestic labor together (cooking, washing, kneading dough)\n"
            "- hetaera: symposium scene, reclining men on couches, woman playing aulos/lyre, festive/intimate\n"
            "- lower class vendor: market/street scene, woman selling food or goods to a customer\n"
            "- Medea: mythological scene with serpent chariot, or infanticide scene, or sorceress with cauldron\n"
            "- young girl: small child figure, often on a grave stele with toys, pet bird, or whimsical objects\n\n"
            "QUOTE-TO-CHARACTER KEY (for the quote-matching question) — VERIFIED CORRECT:\n"
            "Quote A = Spartan runner (mentions Heraia/Heraea race, proud of winning)\n"
            "Quote B = mourner (wails, tears hair for departed loved one)\n"
            "Quote C = maenad (Dionysos goaded her to madness, wild deeds)\n"
            "Quote D = lower class vendor (selling cakes and fruits in the market)\n"
            "Quote E = young girl (died young, left all toys and pets behind)\n"
            "Quote F = woman spinning (finishing spinning wool to start weaving new outfit for festival)\n"
            "Quote G = Medea (son, father's treachery cost you your lives)\n"
            "Quote H = hetaera (tired of music at symposium, just hopes he lets her go home early)\n"
            "Quote I = bride with the groom (wondering what new oikos will be like, will husband be kind)\n"
            "Quote J = slaves working (no freedom, making bread while listening to music)\n\n"
            "IMPORTANT IMAGE IDENTIFICATION NOTE (verified from actual quiz):\n"
            "In the Women's Lives collage: the vendor scene (selling food) may look similar to the spinning scene.\n"
            "Key distinction: vendor = woman at market/counter selling items TO a customer;\n"
            "woman spinning = woman holding distaff/spindle OR seated at loom WITH weights.\n"
            "Do NOT confuse a standing woman holding objects with spinning — check if there is a customer/buyer present.\n\n"
            "Numbers on images indicate position in the collage. "
            "ALWAYS check the open dropdown screenshot to confirm exact available answer choices."
        )

        items_list = items if items else [f"Image {i+1}" for i in range(len(options))]

        # Detect question type: label options vs quote options
        opts_are_quotes = any(o.startswith("Quote") for o in options)

        # Ảnh collage + dropdown
        img_content = _build_image_content(main_images)
        dropdown_content = _build_image_content(dropdown_imgs)

        opts_str = "\n".join(f"  - {o}" for o in options)
        items_str = "\n".join(f"  {it} → ?" for it in items_list)
        fmt_str = "\n".join(f"{it} → [answer]" for it in items_list)

        if opts_are_quotes:
            task_desc = (
                "TASK: Each numbered image shows a Greek woman in a specific role. "
                "Match each image to the Quote (A-J) that character would most likely say.\n\n"
                "Steps:\n"
                "1. For each image number, identify WHICH character/role it depicts "
                "(maenad, Spartan runner, mourner, spinning woman, bride, slaves, hetaera, vendor, Medea, young girl)\n"
                "2. Use the QUOTE-TO-CHARACTER KEY in the system prompt to find the matching quote letter\n"
                "3. Check the open dropdown screenshot to confirm the quote letters available\n"
                "4. Each quote used exactly once\n"
            )
        else:
            task_desc = (
                "TASK: The collage contains numbered artworks. "
                "For each numbered image, identify the scene/figure/role depicted, "
                "then choose the BEST matching label from the dropdown list.\n\n"
                "Steps:\n"
                "1. Look carefully at each numbered image — note clothing, posture, objects, setting\n"
                "2. Use the VISUAL IDENTIFICATION GUIDE in the system prompt\n"
                "3. Check the OPEN DROPDOWN screenshot to confirm exact available labels\n"
                "4. Each label used exactly once\n"
            )

        p1_text = (
            f"Greek Achievement course — Kent State University.\n"
            f"Question text: {q_text}\n\n"
            f"{task_desc}\n"
            f"Available answer choices (also visible in the open dropdown screenshot):\n{opts_str}\n\n"
            f"Items to match:\n{items_str}\n\n"
            f"Provide your answers in this exact format:\n```\n{fmt_str}\n```\n"
            f"Then briefly explain each match."
        )

        console.print("  [dim]Pass 1: Identifying + matching...[/dim]")
        r1 = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=2000,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": (
                    [{"type": "text", "text": p1_text}]
                    + img_content
                    + dropdown_content
                )},
            ],
        )
        draft = r1.choices[0].message.content

        # ── Pass 2: Verify ───────────────────────────────────────────────────
        p2_text = (
            f"Your draft answer:\n```\n{draft}\n```\n\n"
            f"Please verify by checking the OPEN DROPDOWN screenshot again:\n"
            f"1. Every answer must be EXACTLY from this list: {', '.join(options)}\n"
            f"2. Each answer used only once (no duplicates)\n"
            f"3. Each match makes historical/artistic sense\n\n"
            f"If any match seems wrong, correct it. Provide the **FINAL ANSWER**:\n"
            f"```\n{fmt_str}\n```"
        )

        console.print("  [dim]Pass 2: Verifying...[/dim]")
        r2 = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=2000,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": (
                    [{"type": "text", "text": p1_text}]
                    + img_content + dropdown_content
                )},
                {"role": "assistant", "content": draft},
                {"role": "user", "content": (
                    [{"type": "text", "text": p2_text}]
                    + dropdown_content
                )},
            ],
        )
        final = r2.choices[0].message.content

        return f"### Pass 1\n{draft}\n\n---\n\n### ✅ FINAL (verified)\n{final}"

    except Exception as e:
        return f"GPT-4o error: {e}"


# ─── Web-based solver (Canvas Quiz API + GPT-4o, streams to web UI) ──────────

def solve_quiz_api(course_id: int, quiz_id: int, assignment_id: int,
                   api_token: str = "", cookies: list = None,
                   progress_cb=None) -> str:
    """
    Fetch quiz questions via Canvas Quiz API, answer with GPT-4o.
    No Playwright required — works with API token only.
    """
    def emit(msg):
        if progress_cb:
            progress_cb(msg)

    if not OPENAI_API_KEY:
        return "Cần OPENAI_API_KEY trong .env"
    if not cookies:
        return "Chưa có session. Vào dashboard → Sync Canvas trước."

    session_cookies_dict = {
        c["name"]: c["value"] for c in cookies
        if "instructure" in c.get("domain", "")
    }
    api_headers = {"User-Agent": "canvas-app/1.0"}
    if api_token:
        api_headers["Authorization"] = f"Bearer {api_token}"

    # ── 1. Module context (lecture PDFs) ──────────────────────────────────────
    emit("Đang đọc tài liệu module...")
    from agent.assignment_agent import gather_module_context, strip_html
    ctx          = gather_module_context(assignment_id)
    context_text = ctx.get("context_text", "")
    sources      = ctx.get("sources", [])
    module_name  = ctx.get("module_name", "")
    course_name  = ctx.get("course_name", "Unknown Course")
    if sources:
        emit(f"Context: {len(context_text):,} ký tự từ {len(sources)} tài liệu")
    else:
        emit("Không có tài liệu — dùng kiến thức chung")

    # ── 2. Open quiz with Playwright (saved cookies, no re-login) ─────────────
    emit("Đang mở quiz trong trình duyệt...")
    quiz_url   = f"{CANVAS_BASE_URL}/courses/{course_id}/quizzes/{quiz_id}"
    all_questions = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            ctx_pw  = browser.new_context(
                viewport={"width": 1400, "height": 900},
                device_scale_factor=2,
            )
            valid_cookies = [
                {**c, "sameSite": "Lax"}
                if c.get("sameSite") not in ("Strict", "Lax", "None") else c
                for c in cookies
            ]
            ctx_pw.add_cookies(valid_cookies)
            page = ctx_pw.new_page()
            page.goto(quiz_url, wait_until="networkidle", timeout=25000)
            emit(f"Mở: {page.url[-50:]}")

            if "login" in page.url.lower() or "saml" in page.url.lower():
                browser.close()
                return "Session hết hạn — vào dashboard bấm Sync Canvas để đăng nhập lại."

            # Click Take the Quiz / Resume Quiz
            _start_quiz(page)
            time.sleep(1.5)
            emit(f"Sau click: {page.url[-50:]}")

            page_num = 0
            while True:
                page_num += 1
                try:
                    page.wait_for_selector(".question", timeout=12000)
                except PlaywrightTimeout:
                    dbg = _screenshots_dir() / f"quiz_debug_p{page_num}.png"
                    page.screenshot(path=str(dbg))
                    emit(f"Không thấy câu hỏi trang {page_num}. URL: {page.url[-60:]}")
                    break

                # Scroll để load lazy images
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.5)
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(0.5)

                quiz_data  = _extract_quiz_data(page)
                q_elements = page.locator(".question").all()
                emit(f"Trang {page_num}: {len(quiz_data)} câu hỏi")

                for qi, qdata in enumerate(quiz_data):
                    img_paths = _download_images(
                        qdata.get("image_srcs", []),
                        session_cookies_dict, quiz_id, page_num, qi
                    )
                    q_screenshot = None
                    if qi < len(q_elements):
                        try:
                            p2 = _screenshots_dir() / f"q{page_num}_{qi+1}_elem.png"
                            q_elements[qi].screenshot(path=str(p2))
                            q_screenshot = str(p2)
                        except Exception:
                            pass

                    all_questions.append({
                        "index":      len(all_questions) + 1,
                        "text":       qdata.get("text", ""),
                        "items":      qdata.get("items", []),
                        "options":    qdata.get("options", []),
                        "img_paths":  img_paths,
                        "screenshot": q_screenshot,
                    })

                # Next page?
                moved = False
                for sel in ["button:has-text('Next')", "a:has-text('Next')", "#next-button"]:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=1000):
                            btn.click()
                            page.wait_for_load_state("networkidle", timeout=8000)
                            moved = True
                            break
                    except Exception:
                        continue
                if not moved:
                    break

            browser.close()

    except Exception as e:
        return f"Lỗi mở quiz: {e}"

    if not all_questions:
        return "Không đọc được câu hỏi từ quiz. Hãy thử lại sau."

    print(f"[quiz] Đọc được {len(all_questions)} câu hỏi", flush=True)
    emit(f"Đọc được {len(all_questions)} câu hỏi — đang giải...")

    # ── 3. Solve each question ─────────────────────────────────────────────────
    emit("Đang giải từng câu hỏi với GPT-4o...")
    print(f"[quiz] Bắt đầu giải, OPENAI_API_KEY={'set' if OPENAI_API_KEY else 'MISSING'}", flush=True)
    from openai import OpenAI
    ai = OpenAI(api_key=OPENAI_API_KEY)

    system_prompt = (
        f"You are an excellent student in {course_name} at Kent State University. "
        "Answer quiz questions precisely and accurately. "
        "For multiple choice: state the letter and full text of the correct option. "
        "For matching: list each item → its correct match on a new line (format: item → answer). "
        "For short answer: give the exact answer. "
        "For image-based matching: identify each image visually and match to the best option. "
        "Base your answers DIRECTLY on the provided course materials - cite specific details and examples.\n"
        + (f"\n--- COURSE MATERIALS (primary reference) ---\n{context_text[:60000]}" if context_text else "")
    )

    solved = []
    for i, q in enumerate(all_questions):
        q_text   = q.get("text", "")
        items    = q.get("items", [])
        options  = q.get("options", [])
        img_paths = q.get("img_paths", [])
        screenshot = q.get("screenshot")

        emit(f"Câu {i+1}/{len(all_questions)}: {q_text[:55]}...")

        # Build options block
        has_matching = bool(items)
        if has_matching:
            options_block = (
                "Items to match:\n" + "\n".join(f"  {j+1}. {t}" for j, t in enumerate(items))
                + "\n\nAvailable choices:\n" + "\n".join(f"  - {o}" for o in options)
            )
            task = "Match each item to the correct choice. Format:\nitem → answer"
        elif options:
            options_block = "Options:\n" + "\n".join(f"  ({chr(65+j)}) {o}" for j, o in enumerate(options))
            task = "State the letter and full text of the correct answer."
        else:
            options_block = ""
            task = "Answer this question accurately."

        # Build image content
        image_content = _build_image_content(
            [p for p in (img_paths + ([screenshot] if screenshot else [])) if p]
        )

        user_text = (
            f"Question {i+1} of {len(all_questions)}\n\n"
            f"Question: {q_text}\n\n"
            f"{options_block}\n\n"
            f"Task: {task}"
        )
        user_content = [{"type": "text", "text": user_text}] + image_content

        try:
            resp = ai.chat.completions.create(
                model="gpt-4o",
                max_tokens=800,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ],
            )
            answer_text = resp.choices[0].message.content.strip()
            emit(f"✓ Câu {i+1} xong")
        except Exception as e:
            answer_text = f"Lỗi GPT-4o: {e}"
            emit(f"✗ Câu {i+1}: {e}")

        solved.append({
            "index":         i + 1,
            "question":      q_text,
            "options_block": options_block,
            "answer":        answer_text,
            "has_images":    bool(image_content),
        })

    emit(f"Hoàn thành! Đã giải {len(solved)} câu hỏi.")

    # ── 4. Format results as markdown ──────────────────────────────────────────
    lines = [
        f"# Quiz Answers — {module_name or 'Quiz'}",
        f"*{len(solved)} câu hỏi · GPT-4o*\n",
        "---",
    ]
    for s in solved:
        lines.append(f"\n## Câu {s['index']}")
        q_preview = s["question"][:400] + ("..." if len(s["question"]) > 400 else "")
        if q_preview:
            lines.append(f"**Câu hỏi:** {q_preview}\n")
        if s["options_block"]:
            lines.append(s["options_block"] + "\n")
        img_note = " *(có ảnh)*" if s["has_images"] else ""
        lines.append(f"**✅ Đáp án:**{img_note}\n{s['answer']}")
        lines.append("\n---")

    return "\n".join(lines)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _dismiss_popups(page):
    """Close all Canvas popup/tour/help dialogs that may block the quiz."""
    # Try Escape first to close any focused modal
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        pass

    # Ordered list: close inner dialogs first, then outer panels
    dismiss_selectors = [
        # "Come back later!" dialog buttons
        "button:has-text('Done')",
        "button:has-text('Not Now')",
        "button:has-text('No Thanks')",
        # Generic close/X buttons on modals (try aria-label variants)
        "[aria-label='Close']",
        "[aria-label='close']",
        "button[data-testid='close-button']",
        "[data-component='CloseButton']",
        # Help tray close (the X in top-right of Help panel)
        "button[data-testid='help-tray-close-button']",
        # Any button with just an X icon (Canvas uses InstUI)
        "button:has-text('×')",
        "button:has-text('✕')",
        ".ReactModal__Content button:has-text('Close')",
        ".ReactModal__Overlay button",
        # Dismiss student tour
        "button:has-text('Dismiss')",
    ]

    for sel in dismiss_selectors:
        try:
            btns = page.locator(sel).all()
            for btn in btns:
                if btn.is_visible(timeout=300):
                    btn.click()
                    page.wait_for_timeout(400)
        except Exception:
            pass

    # Press Escape once more to close any remaining overlay
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass


def _start_quiz(page):
    # Dismiss popups up to 3 times (some re-appear after closing the first)
    for _ in range(3):
        _dismiss_popups(page)
        page.wait_for_timeout(300)

    # Try normal click first
    for sel in [
        "#take_quiz_link",
        "a.btn:has-text('Take the Quiz')",
        "a.btn:has-text('Take the quiz')",
        "a.btn:has-text('Resume Quiz')",
        "a.btn:has-text('Resume quiz')",
        "button:has-text('Take the Quiz')",
        "button:has-text('Take the quiz')",
        "button:has-text('Resume')",
        "a:has-text('Take the Quiz')",
        "a:has-text('Take the quiz')",
        "a:has-text('Resume Quiz')",
        "a:has-text('Resume quiz')",
        "text=/take the quiz/i",
        "text=/resume quiz/i",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1500):
                console.print(f"  → click: {btn.text_content().strip()}")
                btn.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                return
        except Exception:
            continue

    # Fallback: JavaScript force-click (bypasses any invisible overlay)
    console.print("  → JS force-click take_quiz_link")
    try:
        page.evaluate("""
            () => {
                const link = document.querySelector('#take_quiz_link')
                    || Array.from(document.querySelectorAll('a,button'))
                        .find(el => /take the quiz|resume quiz/i.test(el.textContent));
                if (link) link.click();
            }
        """)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
    except Exception:
        pass
