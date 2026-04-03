"""
Quiz agent: chụp collage ảnh ở zoom cao, download ảnh gốc,
crop từng ô, gửi GPT-4o Vision từng ảnh riêng để nhận diện.
"""
import base64
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
SCREENSHOTS_DIR = BASE_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)


# ─── Entry point ────────────────────────────────────────────────────────────

def solve_quiz(course_id: int, quiz_id: int, assignment_id: int,
               cookies: list, headless: bool = False):
    quiz_url = f"{CANVAS_BASE_URL}/courses/{course_id}/quizzes/{quiz_id}"
    console.print(f"[blue]Mở quiz...[/blue]")

    session_cookies = {c["name"]: c["value"] for c in cookies
                       if "instructure" in c.get("domain", "")}

    with sync_playwright() as p:
        # device_scale_factor=2 → ảnh sắc nét gấp đôi
        browser = p.chromium.launch(headless=headless)
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
        dbg = SCREENSHOTS_DIR / "debug_after_start.png"
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
                    dbg2 = SCREENSHOTS_DIR / f"debug_no_questions_p{page_num}.png"
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
                    p2 = SCREENSHOTS_DIR / f"q{page_num}_{qi+1}_element.png"
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

                // Options từ select đầu tiên
                const sel = q.querySelector('select');
                if (sel) {
                    Array.from(sel.options).forEach(o => {
                        if (o.value) obj.options.push(o.text.trim());
                    });
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
            spath = SCREENSHOTS_DIR / f"dropdown_{quiz_id}_p{page_num}_q{qi+1}_s{i+1}.png"
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
                dest = SCREENSHOTS_DIR / f"orig_{quiz_id}_p{page_num}_q{qi+1}_i{ii+1}.{ext}"
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


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _start_quiz(page):
    for sel in [
        "#take_quiz_link",
        "a.btn:has-text('Take the Quiz')",
        "a.btn:has-text('Resume Quiz')",
        "a:has-text('Take the Quiz')",
        "a:has-text('Resume Quiz')",
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=3000):
                console.print(f"  → {btn.text_content().strip()}")
                btn.click()
                page.wait_for_load_state("networkidle", timeout=15000)
                return
        except Exception:
            continue
