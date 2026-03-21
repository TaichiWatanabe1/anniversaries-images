import logging
import os
from io import BytesIO


import azure.functions as func
from azure.storage.blob import BlobServiceClient
from google import genai
from google.genai import types
from PIL import Image

from anniversaries import fetch_anniversaries, get_today_mmdd, get_today_date

app = func.FunctionApp()


def _get_required_setting(name: str, *, fallback: str | None = None) -> str:
    """Return a non-empty app setting value, raising a clear error if missing."""
    candidates = [name]
    if fallback:
        candidates.append(fallback)

    for key in candidates:
        value = os.environ.get(key)
        if value and value.strip():
            if key != name:
                logging.info("Using app setting '%s' from fallback '%s'.", name, key)
            return value

    fallback_msg = f" (fallback: {fallback})" if fallback else ""
    raise RuntimeError(
        f"Missing required app setting: {name}{fallback_msg}. "
        "Please configure it in Azure Function App settings."
    )


@app.timer_trigger(
    schedule="0 0 15 * * *",  # 毎日 15:00 UTC = 00:00 JST
    arg_name="myTimer",
    run_on_startup=False,
    use_monitor=False,
)
def generate_anniversary_image(myTimer: func.TimerRequest) -> None:
    try:
        logging.info("Anniversary image generation started.")

        gemini_api_key = _get_required_setting("GEMINI_API_KEY")
        public_connection_string = _get_required_setting(
            "PUBLIC_BLOB_CONNECTION_STRING", fallback="AzureWebJobsStorage"
        )
        blob_container_name = os.environ.get("BLOB_CONTAINER_NAME", "output")
        blob_name = os.environ.get("BLOB_NAME", "anniversary_icon.png")
        base_image_blob_name = os.environ.get("BASE_IMAGE_BLOB_NAME", "favicon.png")

        public_blob_client = BlobServiceClient.from_connection_string(public_connection_string)
        base_image_blob = public_blob_client.get_blob_client(
            container=blob_container_name, blob=base_image_blob_name
        )
        base_image = Image.open(BytesIO(base_image_blob.download_blob().readall()))

        yymmdd = get_today_date()
        mmdd = get_today_mmdd()
        items = fetch_anniversaries(mmdd)

        prompt = f"""
        アプリケーションのアイコンを**今日の情報**を元に拡張してください。

        # 今日の情報
        - 日付: {yymmdd}
        - 記念日一覧: {"\n".join(items)}

        """

        client = genai.Client(api_key=gemini_api_key)
        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=[base_image, prompt],
            config=types.GenerateContentConfig(
                response_modalities=["Image"],
                image_config=types.ImageConfig(
                    aspect_ratio="1:1",
                    image_size="2K",
                ),
            ),
        )

        image_part = None
        for part in response.parts:
            if getattr(part, "inline_data", None) is not None:
                image_part = part
            elif getattr(part, "text", None):
                logging.info(part.text)

        if image_part is None:
            raise RuntimeError("画像が返ってきませんでした。プロンプトや入力画像を見直してください。")

        generated_image = image_part.as_image()
        image_bytes = BytesIO()
        generated_image.save(image_bytes, format="PNG")
        image_bytes.seek(0)

        blob_client = public_blob_client.get_blob_client(
            container=blob_container_name, blob=blob_name
        )
        blob_client.upload_blob(image_bytes, overwrite=True)

        logging.info(f"Image saved to blob: {blob_container_name}/{blob_name}")
    except Exception:
        logging.exception("Anniversary image generation failed.")
        raise
