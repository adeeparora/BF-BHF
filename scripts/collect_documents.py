"""Collect public issuer PDFs, preserving provenance and download failures."""
import concurrent.futures, hashlib, json, re, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import requests
from bs4 import BeautifulSoup

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
# Fetch public source pages concurrently with bounded timeouts.
def scan(item):
    company,source=item
    try:
        response=requests.get(source,headers={"User-Agent":"Mozilla/5.0"},timeout=25)
        response.raise_for_status()
        soup=BeautifulSoup(response.text,"html.parser")
        for a in soup.select("a[href]"):
            title=a.get_text(" ",strip=True)
            parent=a.find_parent("li")
            context=parent.get_text(" ",strip=True) if parent else ""
            if "screener.in" in source:
                if title.startswith("Annual Report"):
                    add(company,title,a["href"],source,"annual-reports",title[-4:])
                elif title in ("PPT","Transcript"):
                    period=re.match(r"[A-Za-z]+ [0-9]{4}",context)
                    period=period.group(0) if period else ""
                    add(company,title+" "+period,a["href"],source,"presentations" if title=="PPT" else "concall-transcripts",period)
            elif re.search(r"\\.pdf|/documents/|fmt=pdf|/is/content/",a["href"],re.I):
                card=a.find_parent("div")
                title=(card.get_text(" ",strip=True) if card else title)[:300]
                add(company,title,a["href"],source)
        print("Scanned",source,flush=True)
    except Exception as e:errors.append(dict(source=source,error=str(e)))
sources=[(c,s) for c,ss in SOURCES.items() for s in ss]+[("BF","https://www.screener.in/company/BAJFINANCE/consolidated/"),("BHF","https://www.screener.in/company/BAJAJHFL/")]
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(scan,sources))
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
            response=requests.get(candidate,headers={"User-Agent":"Mozilla/5.0","Referer":row["source"]},timeout=20)
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
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
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
