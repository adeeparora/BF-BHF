"""Collect public issuer PDFs, preserving provenance and download failures."""
import concurrent.futures, hashlib, json, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

ROOT=Path(".")
rows=[]; errors=[]; seen=set()
def add(company,title,url,source,kind=None,period=""):
    url=urljoin(source,url)
    if not url.startswith("https://"): return
    key=(company,url)
    if key in seen:return
    low=(title+" "+unquote(url)).lower()
    if not kind:
        if re.search(r"annual.?report",low):kind="annual-reports"
        elif "transcript" in low:kind="concall-transcripts"
        elif re.search(r"presentation|investor.?day",low):kind="presentations"
        else:return
    if re.search(r"secretarial|annual.return|mgt-7|bfinsec|insurance",low):return
    if re.search(r"schedule|audio|playback|recording|notice",title,re.I):return
    seen.add(key)
    rows.append(dict(company=company,kind=kind,title=title,period=period,url=url,source=source))

SOURCES={
"BF":[
"https://www.aboutbajajfinserv.com/finance-investor-relations-annual-reports",
"https://www.aboutbajajfinserv.com/finance-investor-relations-digital-annual-report",
"https://www.aboutbajajfinserv.com/finance-investor-relations-investor-presentation",
"https://www.aboutbajajfinserv.com/finance-investor-relations-quarterly-earnings-call",
"https://www.bajajfinserv.in/finance-investor-relations-annual-reports",
"https://www.bajajfinserv.in/finance-investor-relations-investor-presentation",
"https://www.bajajfinserv.in/finance-investor-relations-quarterly-earnings-call"],
"BHF":["https://www.bajajhousingfinance.in/annual-reports","https://www.bajajhousingfinance.in/investor-presentation"]}
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(user_agent="Mozilla/5.0")
    for company,symbol in [("BF","BAJFINANCE/consolidated"),("BHF","BAJAJHFL")]:
        source=f"https://www.screener.in/company/{symbol}/"
        try:
            page.goto(source,wait_until="domcontentloaded",timeout=60000)
            page.wait_for_timeout(2000)
            for a in page.locator("#documents a").evaluate_all("""els=>els.map(a=>({title:a.textContent.trim(),url:a.href,context:a.closest('li')?.innerText||''}))"""):
                title=a["title"]; context=a["context"]
                if title.startswith("Annual Report"):add(company,title,a["url"],source,"annual-reports",title[-4:])
                elif title in ("PPT","Transcript"):
                    add(company,title+" "+context.split("\n")[0],a["url"],source,"presentations" if title=="PPT" else "concall-transcripts",context.split("\n")[0])
        except Exception as e:errors.append(dict(source=source,error=str(e)))
    for company,sources in SOURCES.items():
        for source in sources:
            try:
                page.goto(source,wait_until="domcontentloaded",timeout=60000)
                page.wait_for_timeout(3000)
                def extract():
                    # Include download controls and issuer cards, not only visible links.
                    links=page.locator("a,[data-url],[data-href]").evaluate_all("""els=>els.map(a=>({url:a.href||a.getAttribute('data-url')||a.getAttribute('data-href')||'',title:(a.innerText||a.getAttribute('title')||a.closest('div')?.innerText||'').trim().slice(0,400)}))""")
                    for a in links:
                        if re.search(r"\.pdf|/documents/|fmt=pdf|/is/content/",a["url"],re.I):
                            add(company,a["title"],a["url"],source)
                extract()
                selects=page.locator("select")
                for i in range(selects.count()):
                    options=selects.nth(i).locator("option").evaluate_all("els=>els.map(o=>o.value).filter(Boolean)")
                    for value in options:
                        try:
                            selects.nth(i).select_option(value)
                            page.wait_for_timeout(700)
                            extract()
                        except Exception:pass
                # Document cards sometimes expose the PDF only through an onclick URL.
                html=page.content()
                for link in re.findall(r'https?[^\s"<>]+',html):
                    link=link.replace("&amp;","&")
                    if re.search(r"\.pdf|fmt=pdf",link,re.I):add(company,unquote(link.split("/")[-1]),link,source)
            except Exception as e:errors.append(dict(source=source,error=str(e)))
    browser.close()

seed=Path("sources/seed.json")
if seed.exists():
    for x in json.loads(seed.read_text()):add(**x)
Path("catalog").mkdir(exist_ok=True)
Path("catalog/discovered.json").write_text(json.dumps(rows,indent=2))
def download(row):
    r=dict(row); url=row["url"]; candidates=[url]
    if "AnnPdfOpen.aspx" in url:
        name=parse_qs(urlparse(url).query).get("Pname",[""])[0]
        if name:candidates=[f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}",f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}",url]
    attempts=[]
    for candidate in candidates:
        try:
            response=requests.get(candidate,headers={"User-Agent":"Mozilla/5.0","Referer":row["source"]},timeout=50)
            response.raise_for_status()
            data=response.content
            if not data.lstrip().startswith(b"%PDF-"):raise ValueError("Response is not a PDF")
            digest=hashlib.sha256(data).hexdigest()
            label=re.sub(r"[^A-Za-z0-9]+","-",row["title"]).strip("-")[:100] or "document"
            path=Path(row["company"])/row["kind"]/(label+"-"+digest[:10]+".pdf")
            r.update(status="downloaded",path=str(path),sha256=digest,bytes=len(data),resolved_url=response.url)
            return r,data
        except Exception as e:attempts.append(str(e))
    r.update(status="failed",error="; ".join(attempts))
    return r,None
results=[]; hashes={}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    for r,data in pool.map(download,rows):
        if data:
            key=(r["company"],r["sha256"])
            if key in hashes:r["path"]=hashes[key];r["status"]="duplicate"
            else:
                path=Path(r["path"]);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);hashes[key]=str(path)
        results.append(r)
        print(r["company"],r["status"],r["title"],flush=True)
Path("catalog/manifest.json").write_text(json.dumps(results,indent=2))
Path("catalog/source-errors.json").write_text(json.dumps(errors,indent=2))
lines=["# Document index","","Collection date: "+time.strftime("%Y-%m-%d")+" UTC.","","| Company | Type | Document | Status |","|---|---|---|---|"]
for r in results:
    target="../"+r["path"] if "path" in r else r["url"]
    lines.append(f'| {r["company"]} | {r["kind"]} | [{r["title"].replace("|"," ").replace(chr(10)," ")}]({target}) | {r["status"]} |')
lines+=["","## Coverage","","This is the set discovered on the listed public source pages, not a guarantee that every historical document exists. Failed downloads and source errors remain recorded in the JSON catalogs. PDF signatures and SHA-256 hashes are checked; document contents and period labels need review where source metadata is ambiguous.",""]
Path("catalog/INDEX.md").write_text("\n".join(lines))
print(json.dumps({"discovered":len(rows),"unique_pdfs":len(hashes),"failed":sum(r["status"]=="failed" for r in results),"source_errors":len(errors)}))
