import re
import math
from bs4 import BeautifulSoup
import requests
from itertools import zip_longest
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from fastapi import WebSocket

# Function to get page content
def get_page_content(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        return None

# Function to get detailed data from a single page
def get_detail_data(content, selectors):
    soup = BeautifulSoup(content, "html.parser")
    details = {}
    for key, selector in selectors.items():
        element = soup.select_one(selector)
        if element:
            if key == "email":
                details[key] = element["href"].replace("mailto:", "")
            elif key == "socials":
                details[key] = "; ".join(
                    social["href"] for social in soup.select(selector)
                )
            elif key == "ico":
                match = re.search(r"(\d+)", element.get_text(strip=True))
                details[key] = match.group(1) if match else ""
            else:
                text = element.get_text(strip=True)
                if key == "rating_count":
                    text = text.replace(" ", "").strip("()")
                details[key] = text
        else:
            details[key] = ""
    return details

# Function to extract data from the main page
def get_data_from_page(content, selectors):
    soup = BeautifulSoup(content, "html.parser")
    data = []
    rows = zip_longest(
        soup.select(selectors["company"]),
        soup.select(selectors["address"]),
        soup.select(selectors["phone"]),
        soup.select(selectors["link"]),
        fillvalue="",
    )
    for company, address, phone, link in rows:
        row_data = {
            "company": company.get_text(strip=True) if company else "",
            "address": address.get_text(strip=True) if address else "",
            "phone": phone.get_text(strip=True) if phone else "",
            "link": link["href"] if link else "",
        }
        if row_data["link"]:
            detail_selectors = {
                k: v
                for k, v in selectors.items()
                if k not in ["company", "address", "phone", "link"]
            }
            details = get_detail_data(get_page_content(
                row_data["link"]), detail_selectors)
            row_data.update(details)
        data.append(row_data)
    return data

# Function to construct URLs with pagination, preserving query parameters
def construct_url_with_page(base_url, page_number):
    parsed_url = urlparse(base_url)
    query_params = parse_qs(parsed_url.query)
    query_params['page'] = [str(page_number)]
    new_query = urlencode(query_params, doseq=True)
    new_url = urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment)
    )
    return new_url

# Function to process URL and send progress via WebSocket
async def process_url(BASE_URL, websocket: WebSocket):
    SELECTORS = {
        "company": "a.companyTitle:not([rel='noopener'])",
        "address": "div.status a.address",
        "phone": "div.actions span.action.phone.desktop",
        "link": "h3 a.companyTitle.statCompanyDetail[href]:not([rel='noopener'])",
        "rating": "div.value.detailRating a.rating strong",
        "rating_count": "div.value.detailRating a.rating span.ratingCount",
        "socials": "div.value.detailSocialNetworks a",
        "email": "div.value.detailEmail a[href^='mailto:']",
        "detail_phone": "div.value.detailPhone.detailPhonePrimary span[data-dot='origin-phone-number']",
        "ico": "div.value.detailBusinessInfo",
    }

    data = []
    try:
        # Fetch and process main page
        page_content = get_page_content(BASE_URL)
        if not page_content:
            await websocket.send_json({"error": "Failed to fetch the main page."})
            return
        
        # Parse the page content to get total records and pages
        soup = BeautifulSoup(page_content, "html.parser")
        paging_info = soup.select_one('p:-soup-contains("Zobrazujeme")')
        if paging_info:
            # Extracting total records and current range
            total_records = int(paging_info.select('strong')[-1].text)
            current_page_records = paging_info.select('strong')[0].text.split('–')
            start_record = int(current_page_records[0])
            end_record = int(current_page_records[1])

            # Calculate the total pages based on records per page
            records_per_page = end_record - start_record + 1
            total_pages = math.ceil(total_records / records_per_page)
        else:
            await websocket.send_json({"error": "Could not find paging information on the page."})
            return
        
        # Send initial page information to the client
        await websocket.send_json({
            "total_records": total_records,
            "total_pages": total_pages
        })
        
        # Iterate over all pages
        for page_number in range(1, total_pages + 1):
            if page_number > 1:
                page_url = construct_url_with_page(BASE_URL, page_number)
            else:
                page_url = BASE_URL

            # Send the same message that would be printed
            message = f"Fetching content from {page_url}"
            await websocket.send_json({
                "message": message,
                "current_page": page_number,
                "progress": int((page_number / total_pages) * 100)  # Calculate progress
            })

            page_content = get_page_content(page_url)
            if not page_content:
                continue

            page_data = get_data_from_page(page_content, SELECTORS)
            data.extend(page_data)
            await websocket.send_json({"message": f"Fetched {len(data)} records so far"})
        
        await websocket.send_json({
            "data": data,
            "status": "Scraping completed successfully"
        })
    except Exception as e:
        await websocket.send_json({"error": str(e)})
