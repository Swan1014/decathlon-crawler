import os
import json
import time
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ==========================================
# 🌐 글로벌 상태 관리 (중복 탐색 방지용 메모리)
# ==========================================
# 구조: { "카테고리명": { "상품명": "family_id" } }
global_family_registry = {"backpack": {}, "sunglasses": {}, "shoes": {}}
global_family_counters = {"backpack": 0, "sunglasses": 0, "shoes": 0}

# ==========================================
# 🛠️ 1. 유틸리티 & 이미지 다운로드
# ==========================================
def safe_extract(element):
    return element.get_text().strip() if element else ""

def download_images(image_urls, save_folder):
    os.makedirs(save_folder, exist_ok=True)
    saved_paths = []
    
    for i, url in enumerate(image_urls, start=1):
        file_name = f"img{i}.png" 
        file_path = os.path.join(save_folder, file_name)
        try:
            response = requests.get(url, stream=True, timeout=10)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                # JSON에 들어갈 상대 경로 생성
                relative_path = f"images/{os.path.basename(save_folder)}/{file_name}"
                saved_paths.append(relative_path)
        except Exception as e:
            print(f"🚨 이미지 다운로드 에러: {e}")
    return saved_paths

# ==========================================
# 📦 2. 리뷰 수집 (최대 200개 & 익명화)
# ==========================================
def fetch_and_format_reviews(product_id, max_reviews=200):
    headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0.0.0 Safari/537.36",
    }
    all_reviews = []
    start, limit = 0, 10
    
    print(f"📡 [{product_id}] 리뷰 수집 중... (목표: 최대 {max_reviews}개)")
    
    while len(all_reviews) < max_reviews:
        api_url = f"https://www.decathlon.co.kr/api/product/reviews/all?isDecathlonProduct=true&productIdentifier={product_id}&range={start}-{start+limit-1}"
        response = requests.get(api_url, headers=headers)
        
        if response.status_code != 200: break
        
        data = response.json()
        reviews_chunk = data if isinstance(data, list) else data.get('reviews', data.get('items', []))
        if not reviews_chunk: break
            
        for idx, rev in enumerate(reviews_chunk, start=len(all_reviews)+1):
            if len(all_reviews) >= max_reviews: break 
            
            content = rev.get('comment', '')
            rating_data = rev.get('rating', {})
            rating = int(rating_data.get('code', 5)) if isinstance(rating_data, dict) else 5 
            
            formatted_review = {
                "user_id": f"user_{len(all_reviews)+1:03d}",
                "rating": rating,
                "content": str(content)
            }
            all_reviews.append(formatted_review)
            
        start += limit
        time.sleep(0.1)
        
    print(f"✅ 리뷰 {len(all_reviews)}개 수집 완료!")
    return all_reviews

# ==========================================
# 🚀 3. 상품 1개 완벽 크롤링 (정규화 로직 적용)
# ==========================================
def crawl_single_product(url, category):
    print(f"\n🚀 상품 크롤링 시작: {url}")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')                 
    options.add_argument('--no-sandbox')               
    options.add_argument('--disable-dev-shm-usage')    
    options.add_argument('--window-size=1920,1080')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        driver.get(url)
        time.sleep(3)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # --- 상품 기본 정보 파싱 ---
        id_span = soup.find('span', string=lambda text: text and '모델번호:' in text)
        product_id = safe_extract(id_span).replace("모델번호: ", "")
        if not product_id: return

        product_name = safe_extract(soup.find('h1'))

        # --- 카테고리(Breadcrumb) 파싱 ---
        full_category = category
        breadcrumb_list = soup.find('ol', class_='vp-breadcrumbs__list')
        if breadcrumb_list:
            categories = [span.get_text().strip() for span in breadcrumb_list.find_all('span', attrs={'data-testid': 'breadcrumb-text'})]
            if categories and categories[0] == "홈": categories = categories[1:]
            full_category = " > ".join(categories)

        # 🎯 알고리즘 최적화: 이 모델(이름)을 처음 만났는가?
        is_first_encounter = False
        if product_name not in global_family_registry[category]:
            is_first_encounter = True
            global_family_counters[category] += 1
            new_family_id = f"{category}_{global_family_counters[category]:03d}"
            global_family_registry[category][product_name] = new_family_id

        family_id = global_family_registry[category][product_name]
        base_path = f"dataset/products/{category}/{family_id}"
        os.makedirs(base_path, exist_ok=True)

        # --- 상세 설명(model_description) 추출 ---
        model_description = ""
        if is_first_encounter:
            # 1. 기존의 짧은 요약본(h3) 먼저 추출해서 바탕으로 깔기
            desc_div = soup.find('div', class_='css-18x7fir')
            short_desc = " ".join([h3.get_text() for h3 in desc_div.find_all('h3')]) if desc_div else product_name
            model_description += short_desc + "\n\n"

            # 2. 기술 정보(상세 설명) 팝업에서 추가로 추출해서 밑에 이어 붙이기
            try:
                tech_btn = WebDriverWait(driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH, "//h2[contains(text(), '기술 정보')]"))
                )
                driver.execute_script("arguments[0].click();", tech_btn)
                time.sleep(1.5) # 팝업 로딩 대기
                
                popup_soup = BeautifulSoup(driver.page_source, 'html.parser')
                popup_div = popup_soup.find('div', attrs={'data-testid': 'additionalinfo-popup'})
                
                if popup_div:
                    headers = popup_div.find_all('h3')
                    contents = popup_div.find_all('div', class_='css-te085k')
                    for h, c in zip(headers, contents):
                        model_description += f"[{safe_extract(h)}]\n{safe_extract(c)}\n\n"
            except:
                pass
            
            # 앞뒤 쓸데없는 공백 정리
            model_description = model_description.strip()

        # --- 이미지 다운로드 (색상별 폴더) ---
        image_urls = []
        media_wrapper = soup.find('div', class_=lambda c: c and 'GridMedia_wrapper' in c)
        if media_wrapper:
            for img in media_wrapper.find_all('img'):
                src = img.get('src')
                if src and src.startswith("http"): image_urls.append(src)
        
        image_urls = list(dict.fromkeys(image_urls))
        color_folder = os.path.join(base_path, "images", str(product_id)) 
        saved_image_paths = download_images(image_urls, color_folder)

        # --- JSON 파일 업데이트 (실시간 병합) ---
        product_json_path = os.path.join(base_path, "product.json")
        
        # 처음 만난 모델이면 뼈대 생성
        if is_first_encounter:
            product_data = {
                "product_id": family_id,
                "product_name": product_name,
                "model_description": model_description,
                "category": full_category,
                "variants": []
            }
        else:
            # 이미 있으면 기존 뼈대 불러오기
            with open(product_json_path, "r", encoding="utf-8") as f:
                product_data = json.load(f)

        # 현재 색상(Variant) 정보 추가
        product_data["variants"].append({
            "color": str(product_id),
            "image_paths": saved_image_paths
        })

        with open(product_json_path, "w", encoding="utf-8") as f:
            json.dump(product_data, f, ensure_ascii=False, indent=4)

        # --- 리뷰 수집 (처음 만난 모델만 수행!) ---
        if is_first_encounter:
            reviews_data = fetch_and_format_reviews(product_id, max_reviews=200)
            reviews_json_data = {
                "product_id": family_id,
                "reviews": reviews_data
            }
            with open(os.path.join(base_path, "reviews.json"), "w", encoding="utf-8") as f:
                json.dump(reviews_json_data, f, ensure_ascii=False, indent=4)
        else:
            print(f"⏩ [최적화] '{product_name}' 모델의 리뷰는 이미 수집되었으므로 건너뜁니다.")

        print(f"✨ [{product_id}] 크롤링 완료! (그룹: {family_id})")

    except Exception as e:
        print(f"🚨 [{url}] 크롤링 중 에러 발생: {e}")
    finally:
        driver.quit()

# ==========================================
# 🌐 4. 카테고리 싹쓸이 함수 (정밀 스캐너)
# ==========================================
def crawl_category(category_url, category_name):
    print(f"\n📂 [{category_name}] 카테고리 탐색 시작: {category_url}")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')                 
    options.add_argument('--no-sandbox')               
    options.add_argument('--disable-dev-shm-usage')    
    options.add_argument('--window-size=1920,1080')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    product_links_set = set() 

    try:
        driver.get(category_url)
        time.sleep(3)
        
        driver.execute_script("window.scrollTo(0, 0);")
        
        while True:
            tiles = driver.find_elements(By.XPATH, "//a[@data-cy='productTile']")
            for tile in tiles:
                href = tile.get_attribute('href')
                if href and '/p/' in href:
                    product_links_set.add(href)

            before_scroll = driver.execute_script("return window.pageYOffset;")
            driver.execute_script("window.scrollBy(0, 400);")
            time.sleep(0.4) 
            after_scroll = driver.execute_script("return window.pageYOffset;")
            
            if before_scroll == after_scroll:
                try:
                    show_more_btn = driver.find_element(By.XPATH, "//button[@data-cy='Show-More']")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", show_more_btn)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", show_more_btn)
                    time.sleep(3) 
                except:
                    break

        product_links = list(product_links_set)
        print(f"🎯 [{category_name}] 총 {len(product_links)}개의 상품 링크 확보!")

    except Exception as e:
        print(f"🚨 탐색 중 에러: {e}")
    finally:
        driver.quit()

    for i, link in enumerate(product_links, start=1):
        print(f"\n⏳ [{category_name}] {i}/{len(product_links)} 번째 진입...")
        try:
            crawl_single_product(link, category_name)
        except Exception as e:
            print(f"⚠️ {link} 실패: {e}")

# ==========================================
# 🚀 5. 최종 메인 실행부
# ==========================================
if __name__ == "__main__":
    categories_to_scrape = [
        {"name": "backpack", "url": "https://www.decathlon.co.kr/c/%EB%93%B1%EC%82%B0/%EC%9A%A9%ED%92%88/%EA%B0%80%EB%B0%A9.html?itm_source=hp&itm_medium=circlebanner&itm_campaign=hiking-backpack-260219"},
        {"name": "sunglasses", "url": "https://www.decathlon.co.kr/c/%EB%9F%AC%EB%8B%9D/%EC%9A%A9%ED%92%88/%EC%84%A0%EA%B8%80%EB%9D%BC%EC%8A%A4.html?itm_source=hp&itm_medium=circlebanner&itm_campaign=sunglasses-260224"},
        {"name": "shoes", "url": "https://www.decathlon.co.kr/c/%EB%9F%AC%EB%8B%9D/%EB%9F%AC%EB%8B%9D%ED%99%94/%EB%82%A8%EC%84%B1/%EB%A1%9C%EB%93%9C%EB%9F%AC%EB%8B%9D-%EC%A1%B0%EA%B9%85.html"}
    ]

    print("🔥 데카트론 V2 (최적화 & 정규화) 가동! 🔥")
    
    for cat in categories_to_scrape:
        crawl_category(cat["url"], cat["name"])
        
    print("\n🎉 모든 수집이 완벽하게 종료되었습니다!")
