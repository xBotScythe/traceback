"""LoRA fine-tuning script for OSINT intent parsing + summarization.

Uses unsloth for efficient fine-tuning on Apple Silicon.
Exports to GGUF and auto-imports into Ollama.

Can be run standalone or called from the main app via auto_finetune().
"""

import json
import os
import shutil
import subprocess
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(DIR, "output")
TRAIN_FILE = os.path.join(DIR, "train.jsonl")
GGUF_PATH = os.path.join(OUTPUT_DIR, "unsloth.Q4_K_M.gguf")
MODELFILE_PATH = os.path.join(OUTPUT_DIR, "Modelfile")
OLLAMA_MODEL_NAME = "osint-finetuned"

# --- Config ---
BASE_MODEL = "unsloth/Llama-3.2-3B-Instruct"
LORA_R = 16
LORA_ALPHA = 16
LORA_DROPOUT = 0.05
MAX_SEQ_LEN = 1024
EPOCHS = 5
BATCH_SIZE = 2
GRAD_ACCUM = 4
LR = 2e-4

FINETUNE_DEPS = ["unsloth", "datasets", "trl"]


def _install_deps():
    """Install fine-tuning dependencies if missing."""
    missing = []
    for pkg in FINETUNE_DEPS:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"[finetune] Installing dependencies: {', '.join(missing)}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet"] + missing
        )


def _model_exists_in_ollama() -> bool:
    """Check if the fine-tuned model is already in Ollama."""
    if not shutil.which("ollama"):
        return False
    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=10
        )
        return OLLAMA_MODEL_NAME in result.stdout
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return False


def _gguf_exists() -> bool:
    """Check if the GGUF export already exists."""
    return os.path.exists(GGUF_PATH)


def load_data():
    """Load training data from JSONL."""
    from datasets import Dataset

    examples = []
    with open(TRAIN_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))

    formatted = []
    for ex in examples:
        text = (
            f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n"
            f"{ex['instruction']}<|eot_id|>"
            f"<|start_header_id|>user<|end_header_id|>\n"
            f"{ex['input']}<|eot_id|>"
            f"<|start_header_id|>assistant<|end_header_id|>\n"
            f"{ex['output']}<|eot_id|>"
        )
        formatted.append({"text": text})

    return Dataset.from_list(formatted)


def train():
    """Run the full fine-tuning pipeline."""
    from unsloth import FastLanguageModel
    from trl import SFTTrainer, SFTConfig

    print(f"[finetune] Loading base model: {BASE_MODEL}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=MAX_SEQ_LEN,
        load_in_4bit=True,
    )

    print("[finetune] Applying LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=LORA_DROPOUT,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
    )

    print("[finetune] Loading training data...")
    dataset = load_data()
    print(f"[finetune] {len(dataset)} training examples loaded.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=SFTConfig(
            output_dir=OUTPUT_DIR,
            num_train_epochs=EPOCHS,
            per_device_train_batch_size=BATCH_SIZE,
            gradient_accumulation_steps=GRAD_ACCUM,
            learning_rate=LR,
            fp16=False,
            bf16=True,
            logging_steps=1,
            save_strategy="epoch",
            warmup_steps=5,
            weight_decay=0.01,
            lr_scheduler_type="linear",
            dataset_text_field="text",
            max_seq_length=MAX_SEQ_LEN,
        ),
    )

    print("[finetune] Training...")
    trainer.train()

    print(f"[finetune] Saving adapter to {OUTPUT_DIR}")
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    print("[finetune] Exporting to GGUF (q4_k_m)...")
    model.save_pretrained_gguf(
        OUTPUT_DIR,
        tokenizer,
        quantization_method="q4_k_m",
    )

    print("[finetune] GGUF export complete.")


def import_to_ollama():
    """Create Ollama Modelfile and import the fine-tuned model."""
    modelfile_content = f"FROM {GGUF_PATH}\n"
    with open(MODELFILE_PATH, "w") as f:
        f.write(modelfile_content)

    print(f"[finetune] Importing into Ollama as '{OLLAMA_MODEL_NAME}'...")
    subprocess.run(
        ["ollama", "create", OLLAMA_MODEL_NAME, "-f", MODELFILE_PATH],
        check=True,
    )
    print(f"[finetune] Model '{OLLAMA_MODEL_NAME}' ready in Ollama.")


def auto_finetune() -> str | None:
    """Auto-run fine-tuning if needed. Returns model name if fine-tuned model available."""
    # Already imported into Ollama — nothing to do
    if _model_exists_in_ollama():
        return OLLAMA_MODEL_NAME

    # GGUF exists but not imported — just import it
    if _gguf_exists():
        import_to_ollama()
        return OLLAMA_MODEL_NAME

    # Need to train from scratch
    print("[finetune] No fine-tuned model found. Training one now...")
    print("[finetune] This is a one-time setup and may take a few minutes.\n")

    try:
        _install_deps()
        train()
        import_to_ollama()
        return OLLAMA_MODEL_NAME
    except Exception as e:
        print(f"[finetune] Fine-tuning failed: {e}")
        print("[finetune] Falling back to base model.\n")
        return None


if __name__ == "__main__":
    _install_deps()
    train()
    import_to_ollama()
