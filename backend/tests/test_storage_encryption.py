import pytest
import os
import shutil
import tempfile
from services.storage_encryption import (
    derive_user_key,
    encrypt_data,
    decrypt_data,
    write_encrypted_file,
    read_encrypted_file
)

def test_encryption_decryption_cycle():
    user_token = "guest-test-token-12345"
    plaintext = b"Sample resume plaintext containing confidential information"
    
    ciphertext = encrypt_data(plaintext, user_token)
    assert ciphertext != plaintext
    assert len(ciphertext) > len(plaintext)
    
    decrypted = decrypt_data(ciphertext, user_token)
    assert decrypted == plaintext

def test_encryption_with_wrong_key_fails():
    user_token = "guest-user-1"
    wrong_token = "guest-user-2"
    
    plaintext = b"Sensitive resume data"
    ciphertext = encrypt_data(plaintext, user_token)
    
    with pytest.raises(Exception):
        decrypt_data(ciphertext, wrong_token)

def test_write_and_read_encrypted_file():
    temp_dir = tempfile.mkdtemp()
    try:
        user_token = "auth-session-abc-xyz"
        file_path = os.path.join(temp_dir, "master_resume.json")
        payload = b'{"name": "Akhil", "skills": ["Python", "FastAPI"]}'
        
        # Write encrypted
        enc_path = write_encrypted_file(file_path, payload, user_token)
        assert enc_path.endswith(".enc")
        assert os.path.exists(enc_path)
        
        # Verify raw bytes in file are encrypted (not plain JSON)
        with open(enc_path, "rb") as f:
            raw_bytes = f.read()
        assert b"Akhil" not in raw_bytes
        
        # Read back with valid token
        recovered = read_encrypted_file(enc_path, user_token)
        assert recovered == payload
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_storage_purge_of_unencrypted_plaintext():
    """Verify that unencrypted files can be safely wiped after ciphertext is created."""
    temp_dir = tempfile.mkdtemp()
    try:
        user_token = "purge-test-user-999"
        tex_path = os.path.join(temp_dir, "resume.tex")
        pdf_path = os.path.join(temp_dir, "resume.pdf")
        
        with open(tex_path, "wb") as f:
            f.write(b"\\documentclass{article}\\begin{document}Test\\end{document}")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.5 test binary")

        # Write encrypted files
        enc_tex = write_encrypted_file(f"{tex_path}.enc", open(tex_path, "rb").read(), user_token)
        enc_pdf = write_encrypted_file(f"{pdf_path}.enc", open(pdf_path, "rb").read(), user_token)

        # Emulate zero-knowledge post-compilation cleanup guardrail
        if os.path.exists(enc_tex) and os.path.exists(tex_path):
            os.remove(tex_path)
        if os.path.exists(enc_pdf) and os.path.exists(pdf_path):
            os.remove(pdf_path)

        # Ensure only encrypted files remain in storage
        assert not os.path.exists(tex_path)
        assert not os.path.exists(pdf_path)
        assert os.path.exists(enc_tex)
        assert os.path.exists(enc_pdf)

        # Validate that ciphertext can still be read and decrypted cleanly
        decrypted_pdf = read_encrypted_file(enc_pdf, user_token)
        assert decrypted_pdf == b"%PDF-1.5 test binary"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
