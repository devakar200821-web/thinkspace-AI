from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import base64
import pymupdf
from flask import Flask, request, jsonify, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import RequestEntityTooLarge
import requests
import json
import os
import re
import secrets
import sqlite3
from datetime import timedelta

app = Flask(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision").strip() or "llama3.2-vision"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_EXTRACTED_NOTES = 95000
VISION_BATCH_SIZE = 4
MAX_IMAGE_DIMENSION = 2048
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("THINKSPACEAI_DATA_DIR") or os.path.join(
    os.getenv("LOCALAPPDATA", os.path.expanduser("~")),
    "ThinkSpaceAI"
)
DATABASE_PATH = os.path.join(DATA_DIR, "accounts.sqlite3")
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES + 128 * 1024
)

if not os.getenv("FLASK_SECRET_KEY"):
    app.logger.warning("FLASK_SECRET_KEY is unset; sessions will expire when the app restarts.")


@contextmanager
def get_database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    os.makedirs(DATA_DIR, exist_ok=True)
    with get_database() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Please sign in to continue."}), 401
        return view(*args, **kwargs)
    return wrapped


initialize_database()

class UploadedFileError(Exception):
    pass


class DocumentLimitError(Exception):
    pass


class VisionModelUnavailable(Exception):
    pass


@app.errorhandler(RequestEntityTooLarge)
def request_entity_too_large(_):
    return jsonify({"error": "The uploaded file exceeds the 20 MB limit."}), 413


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Enter a valid email address and password."}), 400
    email = data.get("email", "")
    password = data.get("password", "")
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({"error": "Enter a valid email address and password."}), 400

    email = email.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(password) < 8 or len(password) > 128:
        return jsonify({"error": "Password must be between 8 and 128 characters."}), 400

    try:
        with get_database() as connection:
            cursor = connection.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, generate_password_hash(password))
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with this email already exists."}), 409

    session.clear()
    session["user_id"] = user_id
    session.permanent = True
    return jsonify({"id": user_id, "email": email}), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid email or password."}), 401
    email = data.get("email", "")
    password = data.get("password", "")
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify({"error": "Invalid email or password."}), 401

    with get_database() as connection:
        user = connection.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (email.strip().lower(),)
        ).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True
    return jsonify({"id": user["id"], "email": user["email"]})


@app.get("/api/auth/me")
def auth_me():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Please sign in to continue."}), 401

    with get_database() as connection:
        user = connection.execute(
            "SELECT id, email FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
    if not user:
        session.clear()
        return jsonify({"error": "Please sign in to continue."}), 401
    return jsonify({"id": user["id"], "email": user["email"]})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"success": True})


def ollama_json(prompt, response_schema=None, *, images=None, model=None):
    message = {"role": "user", "content": prompt}
    if images:
        message["images"] = images
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": model or MODEL,
            "messages": [message],
            "format": response_schema or "json",
            "stream": False
        },
        timeout=180
    )
    response.raise_for_status()
    content = response.json()["message"]["content"]
    output = json.loads(content)
    if not isinstance(output, dict):
        raise ValueError("Ollama returned a non-object response.")
    return output


def transcribe_image_pages(image_pages):
    transcriptions = []
    for batch_start in range(0, len(image_pages), VISION_BATCH_SIZE):
        batch = image_pages[batch_start:batch_start + VISION_BATCH_SIZE]
        labels = [str(page_number) for page_number, _ in batch]
        prompt = (
            "Transcribe every attached study-note image in order. Include printed and "
            "handwritten text, tables, symbols, and mathematical formulas. Preserve "
            "formulas using LaTeX delimiters such as $...$; do not solve or complete "
            "them. Do not guess unclear handwriting; mark it [unclear]. If a page has "
            "no legible text, return [no legible text]. Return only a JSON object "
            "whose pages array contains one transcription per image, in the same order. "
            f"These are PDF page numbers (or image labels): {', '.join(labels)}."
        )
        response_schema = {
            "type": "object",
            "properties": {
                "pages": {
                    "type": "array",
                    "minItems": len(batch),
                    "maxItems": len(batch),
                    "items": {"type": "string", "minLength": 1}
                }
            },
            "required": ["pages"],
            "additionalProperties": False
        }
        encoded_images = [
            base64.b64encode(image).decode("ascii")
            for _, image in batch
        ]
        try:
            output = ollama_json(
                prompt,
                response_schema,
                images=encoded_images,
                model=VISION_MODEL
            )
        except requests.HTTPError as error:
            response = error.response
            detail = response.text.lower() if response is not None else ""
            if (
                response is not None
                and (
                    (response.status_code == 404 and "model" in detail)
                    or "does not support image" in detail
                    or "image input is not supported" in detail
                )
            ):
                raise VisionModelUnavailable(
                    f"Ollama vision model '{VISION_MODEL}' is not available. "
                    f"Run `ollama pull {VISION_MODEL}` or set OLLAMA_VISION_MODEL to an installed vision model."
                ) from error
            raise

        pages = output.get("pages")
        if (
            not isinstance(pages, list)
            or len(pages) != len(batch)
            or any(not isinstance(page_text, str) or not page_text.strip() for page_text in pages)
        ):
            raise ValueError("Ollama returned an unexpected image transcription.")
        transcriptions.extend(pages)
    return transcriptions


def render_page_for_vision(page):
    width = float(page.rect.width)
    height = float(page.rect.height)
    if width <= 0 or height <= 0:
        raise UploadedFileError("The uploaded document contains an invalid page.")
    scale = min(2.0, MAX_IMAGE_DIMENSION / max(width, height))
    return page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale),
        alpha=False
    ).tobytes("png")


def read_pdf_notes(file_bytes):
    try:
        document = pymupdf.open(stream=file_bytes, filetype="pdf")
    except (pymupdf.FileDataError, ValueError) as error:
        raise UploadedFileError("This PDF could not be opened. Check that it is not damaged or password-protected.") from error

    try:
        if document.page_count == 0:
            raise UploadedFileError("This PDF contains no pages.")
        if document.page_count > MAX_PDF_PAGES:
            raise DocumentLimitError(f"PDFs are limited to {MAX_PDF_PAGES} pages per upload.")

        page_texts = []
        visual_pages = []
        for page_number in range(document.page_count):
            page = document.load_page(page_number)
            selectable_text = page.get_text("text").strip()
            page_texts.append(selectable_text)
            has_images = bool(page.get_images(full=True))
            has_sparse_vector_content = not selectable_text and bool(page.get_drawings())
            if has_images or has_sparse_vector_content:
                visual_pages.append((page_number + 1, render_page_for_vision(page)))

        visual_texts = transcribe_image_pages(visual_pages) if visual_pages else []
        visual_by_page = {
            page_number: visual_text
            for (page_number, _), visual_text in zip(visual_pages, visual_texts)
        }
        sections = []
        for index, selectable_text in enumerate(page_texts):
            page_number = index + 1
            visual_text = visual_by_page.get(page_number, "")
            parts = []
            if selectable_text:
                parts.append(f"Selectable PDF text:\n{selectable_text}")
            if visual_text:
                parts.append(f"Visual transcription (including handwriting/formulas):\n{visual_text}")
            if parts:
                sections.append(f"[Page {page_number}]\n" + "\n\n".join(parts))
        return "\n\n".join(sections), document.page_count
    except (pymupdf.FileDataError, RuntimeError):
        raise UploadedFileError("Could not read one or more PDF pages.") from error
    finally:
        document.close()


def read_image_notes(file_bytes, extension):
    image_type = "jpeg" if extension in {".jpg", ".jpeg"} else "png"
    try:
        document = pymupdf.open(stream=file_bytes, filetype=image_type)
    except (pymupdf.FileDataError, ValueError) as error:
        raise UploadedFileError("This image could not be opened. Use a valid PNG or JPEG file.") from error

    try:
        if document.page_count != 1:
            raise UploadedFileError("Upload one PNG or JPEG image at a time.")
        image = render_page_for_vision(document.load_page(0))
    except (pymupdf.FileDataError, RuntimeError):
        raise UploadedFileError("Could not read the uploaded image.") from error
    finally:
        document.close()

    transcription = transcribe_image_pages([(1, image)])[0]
    return f"[Image transcription]\n{transcription}"


def ollama_error_response(error):
    if isinstance(error, requests.exceptions.ConnectionError):
        return jsonify({"error": "Cannot connect to Ollama. Check that Ollama is running."}), 503
    if isinstance(error, requests.exceptions.Timeout):
        return jsonify({"error": "AI request timed out. Please try again."}), 504
    return jsonify({"error": "Could not generate valid study materials."}), 502


def get_json_string(data, key):
    if not isinstance(data, dict):
        return ""
    value = data.get(key, "")
    return value.strip() if isinstance(value, str) else ""


@app.post("/api/read-document")
@login_required
def read_document():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"error": "Choose a PDF, PNG, or JPEG file to read."}), 400

    extension = Path(uploaded.filename).suffix.lower()
    if extension not in {".pdf", ".png", ".jpg", ".jpeg"}:
        return jsonify({"error": "Supported uploads are PDF, PNG, and JPEG files."}), 415

    file_bytes = uploaded.stream.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return jsonify({"error": "Uploaded files must be 20 MB or smaller."}), 413
    if not file_bytes:
        return jsonify({"error": "The selected file is empty."}), 400

    try:
        if extension == ".pdf":
            notes, page_count = read_pdf_notes(file_bytes)
        else:
            notes = read_image_notes(file_bytes, extension)
            page_count = 1
        if not notes.strip():
            return jsonify({"error": "No readable text was found in the uploaded document."}), 422
        if len(notes) > MAX_EXTRACTED_NOTES:
            return jsonify({
                "error": f"Extracted notes exceed {MAX_EXTRACTED_NOTES:,} characters. Split the document and upload smaller sections."
            }), 413
        return jsonify({
            "filename": Path(uploaded.filename).name,
            "notes": notes,
            "pages": page_count
        })
    except DocumentLimitError as error:
        return jsonify({"error": str(error)}), 413
    except UploadedFileError as error:
        return jsonify({"error": str(error)}), 400
    except VisionModelUnavailable as error:
        return jsonify({"error": str(error)}), 503
    except requests.RequestException as error:
        return ollama_error_response(error)
    except (ValueError, KeyError, TypeError) as error:
        app.logger.warning("Ollama returned an invalid document transcription: %s", error)
        return jsonify({"error": "Ollama could not transcribe the document. Check the vision model and try again."}), 502


@app.post("/api/generate")
@login_required
def generate():
    data = request.get_json(silent=True) or {}
    notes = get_json_string(data, "notes")

    if not notes:
        return jsonify({"error": "Please provide lecture notes."}), 400
    if len(notes) > 100000:
        return jsonify({"error": "Lecture notes must be 100,000 characters or fewer."}), 413

    prompt = f"""
You are ThinkSpaceAI, an AI learning assistant.
Use the lecture notes below to create study materials.

LECTURE NOTES:
{notes}

Return valid JSON with:
- summary: maximum 150 words
- key_terms: array of objects with "term" and "definition"
- flashcards: exactly 10 objects with "question" and "answer"
- prompt_comparison: generate three different summaries of these same notes:
  - zero_shot: use a direct instruction without examples.
  - few_shot: follow the style demonstrated by examples, without adding facts.
  - chain_of_thought: privately identify key ideas and relationships, then provide
    only the concise summary; do not reveal reasoning.
  Each summary must be no more than 150 words. Independently rate each summary
  from 1 to 5 for faithfulness, coverage, and clarity, using the same rubric.
  Include a short rationale for the ratings. Do not expose hidden reasoning.

For few-shot style, use this demonstration only as a format example:
Input: "Rain fills reservoirs. Reservoir water supplies homes."
Summary: "Rain replenishes reservoirs that provide water to homes."

Use this structure:
{{
  "summary": "Summary here",
  "key_terms": [
    {{"term": "Example", "definition": "One-line definition"}}
  ],
  "flashcards": [
    {{"question": "Question", "answer": "Answer"}}
  ],
  "prompt_comparison": {{
    "zero_shot": {{
      "summary": "Summary here",
      "quality": {{
        "faithfulness": 1,
        "coverage": 1,
        "clarity": 1,
        "rationale": "Short rating rationale"
      }}
    }},
    "few_shot": {{
      "summary": "Summary here",
      "quality": {{
        "faithfulness": 1,
        "coverage": 1,
        "clarity": 1,
        "rationale": "Short rating rationale"
      }}
    }},
    "chain_of_thought": {{
      "summary": "Summary here",
      "quality": {{
        "faithfulness": 1,
        "coverage": 1,
        "clarity": 1,
        "rationale": "Short rating rationale"
      }}
    }}
  }}
}}
"""

    variant_schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            "quality": {
                "type": "object",
                "properties": {
                    "faithfulness": {"type": "integer", "minimum": 1, "maximum": 5},
                    "coverage": {"type": "integer", "minimum": 1, "maximum": 5},
                    "clarity": {"type": "integer", "minimum": 1, "maximum": 5},
                    "rationale": {"type": "string", "minLength": 1}
                },
                "required": ["faithfulness", "coverage", "clarity", "rationale"],
                "additionalProperties": False
            }
        },
        "required": ["summary", "quality"],
        "additionalProperties": False
    }
    comparison_methods = ("zero_shot", "few_shot", "chain_of_thought")
    response_schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            "key_terms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string", "minLength": 1},
                        "definition": {"type": "string", "minLength": 1}
                    },
                    "required": ["term", "definition"],
                    "additionalProperties": False
                }
            },
            "flashcards": {
                "type": "array",
                "minItems": 10,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "minLength": 1},
                        "answer": {"type": "string", "minLength": 1}
                    },
                    "required": ["question", "answer"],
                    "additionalProperties": False
                }
            },
            "prompt_comparison": {
                "type": "object",
                "properties": {method: variant_schema for method in comparison_methods},
                "required": list(comparison_methods),
                "additionalProperties": False
            }
        },
        "required": ["summary", "key_terms", "flashcards", "prompt_comparison"],
        "additionalProperties": False
    }

    try:
        output = ollama_json(prompt, response_schema)
        summary = output.get("summary")
        key_terms = output.get("key_terms")
        flashcards = output.get("flashcards")
        comparison = output.get("prompt_comparison")

        if not isinstance(summary, str) or not isinstance(key_terms, list) or not isinstance(comparison, dict):
            return jsonify({"error": "AI returned study materials in an unexpected format."}), 502
        if len(summary.split()) > 150:
            return jsonify({"error": "Generated summary exceeds 150 words."}), 502
        if any(
            not isinstance(comparison.get(method), dict)
            or not isinstance(comparison[method].get("summary"), str)
            or len(comparison[method]["summary"].split()) > 150
            or not isinstance(comparison[method].get("quality"), dict)
            for method in comparison_methods
        ):
            return jsonify({"error": "AI returned summary comparisons in an unexpected format."}), 502
        for method in comparison_methods:
            quality = comparison[method]["quality"]
            if any(
                not isinstance(quality.get(metric), int)
                or isinstance(quality.get(metric), bool)
                or not 1 <= quality[metric] <= 5
                for metric in ("faithfulness", "coverage", "clarity")
            ) or not isinstance(quality.get("rationale"), str):
                return jsonify({"error": "AI returned summary quality ratings in an unexpected format."}), 502
            quality["average_score"] = round(
                sum(quality[metric] for metric in ("faithfulness", "coverage", "clarity")) / 3,
                1
            )
        winner = max(comparison_methods, key=lambda method: comparison[method]["quality"]["average_score"])
        comparison["winner"] = winner
        comparison["winner_score"] = comparison[winner]["quality"]["average_score"]

        if not isinstance(flashcards, list) or len(flashcards) != 10:
            return jsonify({"error": "AI did not generate exactly 10 flashcards."}), 502

        if any(
            not isinstance(term, dict)
            or not isinstance(term.get("term"), str)
            or not isinstance(term.get("definition"), str)
            for term in key_terms
        ):
            return jsonify({"error": "AI returned key terms in an unexpected format."}), 502
        if any(
            not isinstance(card, dict)
            or not isinstance(card.get("question"), str)
            or not isinstance(card.get("answer"), str)
            for card in flashcards
        ):
            return jsonify({"error": "AI returned flashcards in an unexpected format."}), 502

        return jsonify(output)
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        return ollama_error_response(error)


@app.post("/api/tutor")
@login_required
def tutor():
    data = request.get_json(silent=True) or {}
    notes = get_json_string(data, "notes")
    question = get_json_string(data, "question")
    if not notes or not question:
        return jsonify({"error": "Provide lecture notes and a question for the AI tutor."}), 400
    if len(notes) > 100000:
        return jsonify({"error": "Lecture notes must be 100,000 characters or fewer."}), 413

    prompt = f"""You are the ThinkSpaceAI tutor. Answer the student's question clearly and helpfully using the provided notes. If the notes do not contain the answer, say so and provide relevant general context. Do not reveal hidden reasoning. Return JSON with an "answer" string.

LECTURE NOTES:
{notes}

QUESTION:
{question}
"""
    try:
        output = ollama_json(prompt)
        answer = output.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            return jsonify({"error": "AI returned an invalid tutor answer."}), 502
        return jsonify({"answer": answer})
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        return ollama_error_response(error)


@app.post("/api/quiz")
@login_required
def quiz():
    data = request.get_json(silent=True) or {}
    notes = get_json_string(data, "notes")
    if not notes:
        return jsonify({"error": "Please provide lecture notes to generate a quiz."}), 400
    if len(notes) > 100000:
        return jsonify({"error": "Lecture notes must be 100,000 characters or fewer."}), 413

    prompt = f"""Create exactly 5 multiple-choice quiz questions using only the student's notes. Every question must have exactly 4 different options. Set "answer_index" to the zero-based index (0, 1, 2, or 3) of the correct option. Return only the requested JSON object. Do not include markdown, explanations, or hidden reasoning.

LECTURE NOTES:
{notes}
"""
    quiz_schema = {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "minLength": 1},
                        "options": {
                            "type": "array",
                            "minItems": 4,
                            "maxItems": 4,
                            "uniqueItems": True,
                            "items": {"type": "string"}
                        },
                        "answer_index": {"type": "integer", "minimum": 0, "maximum": 3}
                    },
                    "required": ["question", "options", "answer_index"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["questions"],
        "additionalProperties": False
    }
    try:
        output = ollama_json(prompt, quiz_schema)
        questions = output.get("questions")
        if not isinstance(questions, list) or len(questions) != 5:
            return jsonify({"error": "AI did not generate exactly 5 quiz questions."}), 502
        for item in questions:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("question"), str)
                or not isinstance(item.get("options"), list)
                or len(item["options"]) != 4
                or len(set(item["options"])) != 4
                or any(not isinstance(option, str) for option in item["options"])
                or not isinstance(item.get("answer_index"), int)
                or isinstance(item.get("answer_index"), bool)
                or not 0 <= item["answer_index"] < len(item["options"])
            ):
                return jsonify({"error": "AI returned quiz questions in an unexpected format."}), 502
            item["answer"] = item["options"][item.pop("answer_index")]
        return jsonify({"questions": questions})
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        return ollama_error_response(error)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
    )
