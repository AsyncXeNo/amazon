from __future__ import annotations

import os
import time
import tempfile
import asyncio

from apify import Actor, Request
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from .captcha import solve_text_captcha, report_incorrect

# VARIABLES
CAPTCHAS_SOLVED = 0


# UTILITY FUNCTIONS
def check_for_captcha(driver: webdriver.Chrome) -> bool:
    try:
        driver.find_element(By.XPATH, '//h4[text()="Type the characters you see in this image:"]')
        return True
    except:
        return False


def solve_captcha(driver: webdriver.Chrome, logger, current_try: int = 1):
    global CAPTCHAS_SOLVED

    if current_try > 5:
        logger.error('Failed to solve captcha after 5 attempts')
        return

    captcha_img = driver.find_element(By.CSS_SELECTOR, '.a-row img')

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
        captcha_img.screenshot(tmp_file.name)
        captcha_path = tmp_file.name

    code, captcha_id = solve_text_captcha(captcha_path, logger)

    try:
        os.remove(captcha_path)
    except:
        pass

    driver.find_element(By.ID, 'captchacharacters').send_keys(code)
    driver.find_element(By.TAG_NAME, 'button').click()

    time.sleep(0.5)

    if check_for_captcha(driver):
        report_incorrect(captcha_id, logger)
        return solve_captcha(driver, logger, current_try + 1)
    else:
        logger.info('Captcha solved successfully')
        CAPTCHAS_SOLVED += 1
        return


# Main function
async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        start_urls = actor_input.get('urls')

        if not start_urls:
            Actor.log.info('No start URLs specified in actor input, exiting...')
            await Actor.exit()

        request_queue = await Actor.open_request_queue()

        for start_url in start_urls:
            url = start_url.get('url')
            Actor.log.info(f'Enqueuing {url} ...')
            new_request = Request.from_url(url)
            await request_queue.add_request(new_request)

        Actor.log.info('Launching Chrome WebDriver...')
        chrome_options = ChromeOptions()

        if Actor.config.headless:
            chrome_options.add_argument('--headless')

        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--window-size=1920,1080')
        driver = webdriver.Chrome(options=chrome_options)

        data = []

        while request := await request_queue.fetch_next_request():
            url = request.url

            Actor.log.info(f'Scraping {url} ...')

            time.sleep(0.5)

            try:
                await asyncio.to_thread(driver.get, url)
                
                # Check captcha
                if check_for_captcha(driver):
                    solve_captcha(driver, Actor.log)

                # Check for reload
                try:
                    product_div = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located(
                            (By.ID, 'ppd')
                        )
                    )
                except TimeoutException:
                    driver.refresh()
                    try:
                        product_div = WebDriverWait(driver, 2).until(
                            EC.presence_of_element_located(
                                (By.ID, 'ppd')
                            )
                        )
                    except TimeoutException:
                        data.append({
                            'url': url,
                            'mrp': 'NA',
                            'sp': 'NA',
                            'seller': 'NA',
                            'deal tag': 'NA',
                            'expiry date': 'NA'
                        })
                        Actor.log.info(data[-1])
                        continue

                # Extract product information
                try:
                    driver.find_element(By.CSS_SELECTOR, '#dealBadgeSupportingText')
                    deal_tag = 'Yes'
                except Exception:
                    deal_tag = 'No'

                expiry_date = driver.find_element(By.CSS_SELECTOR, '#expiryDate_feature_div').get_attribute('innerText').strip().split(':')[-1].strip()

                seller = driver.find_element(By.CSS_SELECTOR, '#merchantInfoFeature_feature_div a').get_attribute('innerText').strip()
                
                try:
                    apex_desktop_div = driver.find_element(By.CSS_SELECTOR, '#apex_desktop_newAccordionRow')
                except:
                    try:
                        apex_desktop_div = driver.find_element(By.CSS_SELECTOR, '#apex_desktop')
                    except:
                        data.append({
                            'url': url,
                            'mrp': 'NA',
                            'sp': 'NA',
                            'seller': seller,
                            'deal tag': deal_tag,
                            'expiry date': expiry_date
                        })
                        continue

                try:
                    basis_price = float(apex_desktop_div.find_element(By.CSS_SELECTOR, ' .basisPrice .a-offscreen').get_attribute('innerText').replace(',', '').strip().strip('₹'))
                except:
                    basis_price = None

                try:
                    price_to_pay = float(apex_desktop_div.find_element(By.CSS_SELECTOR, '.priceToPay .a-price-whole').get_attribute('innerText').replace(',', '').strip().strip('₹'))
                except:
                    try:
                        price_to_pay = float(apex_desktop_div.find_element(By.CSS_SELECTOR, '.apexPriceToPay .a-offscreen').get_attribute('innerText').replace(',', '').strip().strip('₹'))
                    except:
                        price_to_pay = None

                basis_price = basis_price if basis_price else 'NA'
                price_to_pay = price_to_pay if price_to_pay else 'NA'
                data.append({
                    'url': url,
                    'mrp': basis_price,
                    'sp': price_to_pay,
                    'seller': seller,
                    'deal tag': deal_tag,
                    'expiry date': expiry_date
                })
                Actor.log.info(data[-1])

            except Exception:
                Actor.log.exception(f'Cannot extract data from {url}.')
                data.append({
                    'url': url,
                    'mrp': 'NA',
                    'sp': 'NA',
                    'seller': 'NA',
                    'deal tag': 'NA',
                    'expiry date': 'NA'
                })
                Actor.log.info(data[-1])

            finally:
                await request_queue.mark_request_as_handled(request)
        
        driver.quit()

        await Actor.push_data({
            'data': data,
            'captchas_solved': CAPTCHAS_SOLVED
        })