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
            response = requests.get(url, stream=True)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                relative_path = f"images/{os.path.basename(save_folder)}/{file_name}"
                saved_paths.append(relative_path)
        except Exception as e:
            print(f"🚨 이미지 다운로드 에러: {e}")
    return saved_paths

# ==========================================
# 📦 2. 리뷰 수집 & 엄격한 JSON 포맷팅 (테스트용 제한)
# ==========================================
def fetch_and_format_reviews(product_id, max_reviews=20):
    headers = {
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0.0.0 Safari/537.36",
    }
    all_reviews = []
    start, limit = 0, 10
    
    print(f"📡 [{product_id}] 리뷰 API 고속 수집 중... (테스트 모드: 최대 {max_reviews}개 제한)")
    
    while len(all_reviews) < max_reviews:
        api_url = f"https://www.decathlon.co.kr/api/product/reviews/all?isDecathlonProduct=true&productIdentifier={product_id}&range={start}-{start+limit-1}"
        response = requests.get(api_url, headers=headers)
        
        if response.status_code != 200: break
        
        data = response.json()
        reviews_chunk = data if isinstance(data, list) else data.get('reviews', data.get('items', []))
        if not reviews_chunk: break
            
        for idx, rev in enumerate(reviews_chunk, start=len(all_reviews)+1):
            if len(all_reviews) >= max_reviews: 
                break 
            
            # 리뷰 내용 파싱
            content = rev.get('comment', '')
            
            # 리뷰 별점 파싱 (구조화된 딕셔너리 대응)
            rating_data = rev.get('rating', {})
            if isinstance(rating_data, dict):
                rating = int(rating_data.get('code', 5))
            else:
                rating = 5 
            
            # 유학생 요구사항 맞춤형 구조
            formatted_review = {
                "user_id": f"user_{idx:03d}",
                "rating": rating,
                "content": str(content)
            }
            all_reviews.append(formatted_review)
            
        start += limit
        time.sleep(0.1)
        
    print(f"✅ [{product_id}] 리뷰 {len(all_reviews)}개 수집 완료!")
    return all_reviews

# ==========================================
# 🚀 3. 상품 1개 완벽 크롤링
# ==========================================
def crawl_single_product(url, category):
    print(f"\n🚀 상품 크롤링 시작: {url}")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless') # 확인 끝나면 화면 끄고 돌리는 걸 추천!
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        driver.get(url)
        time.sleep(3)
        
        for _ in range(2): 
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(0.5)
            
        try:
            WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '기술 정보')]"))).click()
            WebDriverWait(driver, 2).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '구성/추천')]"))).click()
        except: pass
        time.sleep(1)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # --- 상품 기본 정보 파싱 ---
        id_span = soup.find('span', string=lambda text: text and '모델번호:' in text)
        product_id = safe_extract(id_span).replace("모델번호: ", "")
        if not product_id:
            print("⚠️ 상품 ID를 찾을 수 없습니다. 스킵합니다.")
            return

        product_name = safe_extract(soup.find('h1'))
        
        desc_div = soup.find('div', class_='css-18x7fir')
        model_desc = " ".join([h3.get_text() for h3 in desc_div.find_all('h3')]) if desc_div else product_name

        # --- 카테고리(Breadcrumb) 파싱 ---
        full_category = ""
        breadcrumb_list = soup.find('ol', class_='vp-breadcrumbs__list')
        
        if breadcrumb_list:
            categories = [span.get_text().strip() for span in breadcrumb_list.find_all('span', attrs={'data-testid': 'breadcrumb-text'})]
            if categories and categories[0] == "홈":
                categories = categories[1:]
            full_category = " > ".join(categories)
            
        if not full_category:
            full_category = category

        # --- 폴더 구조 생성 ---
        base_path = f"dataset/products/{category}/{product_id}"
        os.makedirs(base_path, exist_ok=True)
        
        # --- 이미지 다운로드 (🔥 순수 사진 컨테이너 탐색) ---
        image_urls = []
        media_wrapper = soup.find('div', class_=lambda c: c and 'GridMedia_wrapper' in c)
        
        if media_wrapper:
            img_tags = media_wrapper.find_all('img')
            for img in img_tags:
                src = img.get('src')
                if src and src.startswith("http"):
                    image_urls.append(src)
        
        image_urls = list(dict.fromkeys(image_urls))

        print(f"🖼️ [{product_id}] 순수 상품 이미지 {len(image_urls)}장 다운로드 중...")
        color_folder = os.path.join(base_path, "images", str(product_id)) 
        saved_image_paths = download_images(image_urls, color_folder)

        # --- product.json 작성 ---
        product_json_data = {
            "product_id": str(product_id),
            "product_name": product_name,
            "category": full_category,
            "variants": [
                {
                    "color": str(product_id), 
                    "model_description": model_desc,
                    "image_paths": saved_image_paths 
                }
            ]
        }
        with open(os.path.join(base_path, "product.json"), "w", encoding="utf-8") as f:
            json.dump(product_json_data, f, ensure_ascii=False, indent=4)
            
        # --- 리뷰 수집 및 reviews.json 작성 ---
        reviews_data = fetch_and_format_reviews(product_id)
        
        if len(reviews_data) < 5:
            print(f"⚠️ [경고] [{product_id}] 리뷰가 5개 미만({len(reviews_data)}개)입니다.")
            
        reviews_json_data = {
            "product_id": str(product_id),
            "reviews": reviews_data
        }
        with open(os.path.join(base_path, "reviews.json"), "w", encoding="utf-8") as f:
            json.dump(reviews_json_data, f, ensure_ascii=False, indent=4)

        print(f"✨ [{product_id}] 크롤링 완벽 성공! (저장 폴더: {base_path})")

    except Exception as e:
        print(f"🚨 [{url}] 크롤링 중 에러 발생: {e}")
    finally:
        driver.quit()

# ==========================================
# 🌐 4. 카테고리 싹쓸이 함수 (정밀 스캐너 완벽 대응)
# ==========================================
def crawl_category(category_url, category_name):
    print(f"\n📂 [{category_name}] 카테고리 탐색을 시작합니다: {category_url}")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    product_links_set = set() 

    try:
        driver.get(category_url)
        time.sleep(3)
        
        # 맨 위에서부터 스캔 시작
        driver.execute_script("window.scrollTo(0, 0);")
        print("⬇️ 정밀 스캐너 가동! 화면을 400px씩 천천히 훑으며 링크를 줍습니다...")
        
        while True:
            # 1. 현재 화면에 보이는 가방 링크 싹쓸이 (Selenium으로 직접 추출)
            tiles = driver.find_elements(By.XPATH, "//a[@data-cy='productTile']")
            for tile in tiles:
                href = tile.get_attribute('href') # Selenium은 절대경로(https://...)를 자동 반환함
                if href and '/p/' in href:
                    product_links_set.add(href)

            # 2. 스크롤 내리기 전의 현재 위치 저장
            before_scroll = driver.execute_script("return window.pageYOffset;")
            
            # 3. 딱 400px (가방 1줄 정도 높이)만 부드럽게 스크롤
            driver.execute_script("window.scrollBy(0, 400);")
            time.sleep(0.4) # 새 가방이 렌더링될 시간 대기
            
            # 4. 스크롤 후 위치 확인
            after_scroll = driver.execute_script("return window.pageYOffset;")
            
            # 5. 스크롤 전과 후의 위치가 같다면? -> 현재 로딩된 20개 뭉치의 '바닥'에 도달한 것!
            if before_scroll == after_scroll:
                try:
                    # 바닥에 닿았으니 '더보기' 버튼 찾기
                    show_more_btn = driver.find_element(By.XPATH, "//button[@data-cy='Show-More']")
                    
                    # 버튼을 화면 중앙에 맞춘 후 클릭 (클릭 씹힘 방지)
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", show_more_btn)
                    time.sleep(0.5)
                    driver.execute_script("arguments[0].click();", show_more_btn)
                    
                    print(f"🖱️ '더보기' 클릭! (현재까지 모은 링크: {len(product_links_set)}개)")
                    time.sleep(3) # 추가 상품이 아래에 덧붙여질 때까지 넉넉히 대기
                except:
                    # 바닥에 닿았는데 '더보기' 버튼마저 없다면? -> 전체 상품 로딩 끝!
                    print(f"✅ 바닥 도달! 더 이상 숨겨진 상품이 없습니다.")
                    break

        product_links = list(product_links_set)
        print(f"🎯 [{category_name}] 총 {len(product_links)}개의 상품 링크를 완벽하게 확보했습니다!")

    except Exception as e:
        print(f"🚨 카테고리 탐색 중 에러 발생: {e}")
    finally:
        driver.quit()

    # --- 수집된 링크 크롤링 시작 ---
    for i, link in enumerate(product_links, start=1):
        print(f"\n⏳ [{category_name}] {i}/{len(product_links)} 번째 상품 크롤링 진입...")
        try:
            crawl_single_product(link, category_name)
        except Exception as e:
            print(f"⚠️ {link} 크롤링 실패 (다음 상품으로 넘어갑니다): {e}")

# ==========================================
# 🚀 5. 최종 메인 실행부
# ==========================================
if __name__ == "__main__":
    categories_to_scrape = [
        {
            "name": "backpack",
            "url": "https://www.decathlon.co.kr/c/%EB%93%B1%EC%82%B0/%EC%9A%A9%ED%92%88/%EA%B0%80%EB%B0%A9.html?itm_source=hp&itm_medium=circlebanner&itm_campaign=hiking-backpack-260219"
        },
        {
            "name": "sunglasses",
            "url": "https://www.decathlon.co.kr/c/%EB%9F%AC%EB%8B%9D/%EC%9A%A9%ED%92%88/%EC%84%A0%EA%B8%80%EB%9D%BC%EC%8A%A4.html?itm_source=hp&itm_medium=circlebanner&itm_campaign=sunglasses-260224"
        },
        {
            "name": "shoes",
            "url": "https://www.decathlon.co.kr/c/%EB%9F%AC%EB%8B%9D/%EB%9F%AC%EB%8B%9D%ED%99%94/%EB%82%A8%EC%84%B1/%EB%A1%9C%EB%93%9C%EB%9F%AC%EB%8B%9D-%EC%A1%B0%EA%B9%85.html"
        }
    ]

    print("🔥 데카트론 대규모 데이터 수집 파이프라인 가동! 🔥")
    
    for cat in categories_to_scrape:
        crawl_category(cat["url"], cat["name"])
        
    print("\n🎉 모든 카테고리의 데이터 수집이 완벽하게 종료되었습니다!")
