import os

from twocaptcha import TwoCaptcha
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('TWOCAPTCHA_API_KEY')
solver = TwoCaptcha(API_KEY)


def solve_text_captcha(path_to_image, logger):
    logger.debug('Sending image to 2Captcha for solving')
    for attempt in range(5):
        try:
            result = solver.normal(path_to_image)
            os.remove(path_to_image)
            logger.debug('Received response from 2Captcha, returning solution')
            return result['code'], result['captchaId']
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt == 4:
                logger.error(f'5 consequent API requests failed. Something is wrong. Returning empty string.')
                os.remove(path_to_image)
                return ""

def report_incorrect(id, logger):
    # Report the image as incorrect
    try:
        solver.report(id, False)
        logger.debug(f"Captcha ID {id} reported as incorrect to 2Captcha. (This is important to save costs)")
    except Exception as e:
        logger.warning(f"Failed to report captcha ID {id} as incorrect: {e}")