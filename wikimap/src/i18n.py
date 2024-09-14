import os
import json
import logging
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv, find_dotenv
import deepl

from ..config import language_codes as code
from .language_context import language_context


load_dotenv(find_dotenv(), override=True)
logger = logging.getLogger(__name__)
dashapp_rootdir = Path(__file__).resolve().parents[2]

# make the dictionary available to the whole app, so not each and every
# string that gets translated at app init triggers loading the json data:
dictionary_path = dashapp_rootdir / "i18n" / "dictionary.json"
multiling_dictionary = json.loads(dictionary_path.read_text())


def get_biling_dictionary(multiling_dictionary, language):
    """ """
    logger.info(f"get_biling_dictionary(): {language}")
    return {
        str(entry["DE"]): str(entry[code[language]])
        for entry in multiling_dictionary
        if "DE" in entry and code[language] in entry
    }


def get_translations(labels: pd.Series) -> None:
    """
    Check voting labels for presence of their 'tgt_lang' translation in our
    dictionary, and if missing, translate them and store them right there.
    This only ensures presence; for the function that returns translations,
    see => translate_labels().
    """
    current_language = language_context.get_language()

    # load label dictionary and set to target language:
    dictionary_path = dashapp_rootdir / "i18n" / "dictionary.json"
    dictionary = json.loads(dictionary_path.read_text())
    src = code["de"]
    tgt = code[current_language]
    logger.info(f"Dictionary has {len(dictionary)} entries.")

    # identify new labels (not in dict or not in the desired language):
    data_labels = labels.unique()
    new_labels = [label for label in data_labels if label not in dictionary]

    # do the translating and put it into the global dictionary:
    if new_labels:
        auth_key = os.getenv("DEEPL_AUTH_KEY", None)
        if auth_key:
            logger.info(f"Translating {len(new_labels)} new labels.")
            translator = deepl.Translator(auth_key)
            # new_entries: {"lorem": "ipsum", ...}
            new_entries = {
                key: {
                    tgt: translator.translate_text(
                        key, target_lang=tgt, source_lang=src
                    ).text
                }
                for key in new_labels
            }

            # bring new entries into the dictionary:
            logger.info(f"Adding {len(new_entries)} new entries to the dictionary.")
            for k, v in new_entries.items():
                if k in dictionary:
                    # entry exisits, but add this new language:
                    dictionary[k][tgt] = v
                else:
                    # add completely new entry:
                    dictionary[k] = {tgt: v}

            json.dump(
                dictionary,
                open(dictionary_path, "w"),
                indent=4,
                ensure_ascii=False,
            )

        else:
            logger.warning("No DeepL key found. Translations will not be available.")
    else:
        logger.info("No new labels found. No translation needed.")


def dict2list(dct: dict, key) -> list:
    """
    Turn a dict of the form
    {"lorem": {"A": "ipsum", "B": "dolor", ...}, ...}
    into
    [ {"L": "lorem", "A": "ipsum", "B": "dolor, ...}, ... ].
    "L" as an additional key to every dict must be specified as argument.

    :param dict: the dictionary to transform
    :param key: the new key to all component dicts
    :return: list of dicts
    """
    out = []
    for k, v in dct.items():
        assert isinstance(v, dict)
        this_entry = v
        this_entry[key] = k
        out.append(this_entry)

    return out


def list2dict(lst: list, key) -> dict:
    """
    Turn a list of dicts into a dict of dicts by taking one key (typically a
    language code) and turning its value into the key for each dict.
    Turn form
    [ {"L": "lorem", "A": "ipsum", "B": "dolor, ...}, ... ]
    into
    {"lorem": {"A": "ipsum", "B": "dolor", ...}, ...}.
    If "key" is not in an element dict, this dict gets ignored.

    :param list: the list of dicts to transform
    :param key: the key among dict keys whose value becomes each component
        dict's identifier.
    :return: dict of dicts
    """
    out = {}
    for cdict in lst:
        assert isinstance(cdict, dict)
        if key in cdict.keys():
            this_entry = {key: {k: v for k, v in cdict.items() if k != key}}
            out.update(this_entry)

    return out


def load_current_dict(current_language: str = "en") -> dict:
    """
    Load the master dictionary, bring into simple form:
    {"lorem": {"en": "ipsum"}, ...} => {"lorem": "ipsum", ...}
    """
    dictionary_path = dashapp_rootdir / "i18n" / "dictionary.json"

    tgt = code[current_language]

    master_dict = json.loads(dictionary_path.read_text())
    dictionary = {k: v[tgt] for k, v in master_dict.items()}

    return dictionary


def save_current_dict(dictionary, current_language: str = "en") -> None:
    """
    Restore original dictionary form and save to JSON.
    """
    dictionary_path = dashapp_rootdir / "i18n" / "dictionary.json"
    
    tgt = code[current_language]

    master_dict = {k: {tgt: v} for k, v in dictionary.items()}
    json.dump(master_dict, open(dictionary_path, "w"), ensure_ascii=False, indent=4)


def translate_series(series: pd.Series) -> pd.Series:
    """
    Translate a series of strings into the current language.
    """
    current_language = language_context.get_language()

    if current_language == "de":
        return series
    
    dictionary = load_current_dict(current_language)

    return series.replace(dictionary)


def translate(text: str) -> str:
    """
    Return a previously-cached translation for the given German string. If the
    current language is "de", just return the input string unchanged. Else,
    if no translation is found, get it from DeepL and store it in both
    the bilingual and multilingual dictionaries.

    :param text: the string to translate
    :param src_lang: the source language. Uses our app codes, "de", "en", etc.
    :param tgt_lang: the target language. Uses our app codes, "de", "en", etc.
    :return: the translated string
    """
    current_language = language_context.get_language()

    if current_language == "de":
        return text
    
    if text is None:
        return None

    dictionary = load_current_dict(current_language)

    # if string is in translation memory, return translation:
    if text in dictionary:
        translated_text = dictionary.get(text)
    else:
        # if string is missing, get it from DeepL and store in TM:
        translated_text = request_translation(text)
        dictionary[text] = translated_text
        save_current_dict(dictionary, current_language)

    if translated_text is None:
        logger.error(
            f"No translation found for '{text[0:30]}' in {current_language}, "
            "neither in our own dict nor at DeepL."
        )
        return text

    return translated_text


def request_translation(text: str) -> str:
    """
    Query DeepL API for translation of text into current_language. Save the
    returned string in the bilingual dictionary.
    """
    current_language = language_context.get_language()

    auth_key = os.getenv("DEEPL_AUTH_KEY", None)

    if auth_key:
        logger.info(
            f"Requesting translation for '{text[0:30]}"
            f"{'[...]' if len(text) > 30 else ''}'"
        )
        translator = deepl.Translator(auth_key)

        translated_text = translator.translate_text(
            text,
            target_lang=code[current_language],
            source_lang="DE",
        ).text

    else:
        logger.warning("No DeepL key found. New translations will not be available.")
        translated_text = text

    return translated_text
