#!/usr/bin/env python3
"""
Debug script to see what's on Adelaide's players page
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import time

chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')

driver = webdriver.Chrome(options=chrome_options)

try:
    url = "https://www.afc.com.au/players"
    print(f"Loading: {url}")
    driver.get(url)
    time.sleep(4)
    
    # Scroll to load content
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(2)
    
    # Get all links
    links = driver.find_elements(By.TAG_NAME, 'a')
    print(f"\nFound {len(links)} total links")
    
    # Filter for player links
    player_links = []
    for link in links:
        href = link.get_attribute('href')
        text = link.text.strip()
        
        if href and '/player' in href.lower():
            player_links.append((text, href))
    
    print(f"\nFound {len(player_links)} player links:")
    for text, href in player_links[:20]:  # Show first 20
        print(f"  '{text}' -> {href}")
    
    # Look for Jordan Dawson specifically
    print("\n\nSearching for 'dawson' in page...")
    for link in links:
        href = link.get_attribute('href') or ''
        text = link.text.lower()
        
        if 'dawson' in href.lower() or 'dawson' in text:
            print(f"  FOUND: '{link.text}' -> {href}")

finally:
    driver.quit()
