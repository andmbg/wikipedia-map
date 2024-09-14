import threading
from flask import g, has_request_context
import logging


logger = logging.getLogger(__name__)


class LanguageContext:
    _local = threading.local()

    @classmethod
    def set_language(cls, language):
        logger.info(f"Setting language to {language}")

        if has_request_context():
            g.language = language
        else:
            cls._local.language = language

    @classmethod
    def get_language(cls):
        if has_request_context():
            current_lang = getattr(g, "language", "de")
        else:
            current_lang = getattr(cls._local, "language", "de")
        
        # logger.info(f"Current language: {current_lang}")
        return current_lang

language_context = LanguageContext()
