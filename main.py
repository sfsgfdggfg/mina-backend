from pydantic import BaseModel, Field
from typing import Optional
import os
from fastapi import FastAPI, HTTPException
from openai import OpenAI

class LogisticsInquiry(BaseModel):
    pol: Optional[str] = Field(default="Belirtilmemiş", description="Port of Loading / Yükleme Limanı")
    pod: Optional[str] = Field(default="Belirtilmemiş", description="Port of Discharge / Tahliye Limanı")
    volume: Optional[str] = Field(default="Belirtilmemiş", description="Konteyner tipi ve adedi")
    commodity: Optional[str] = Field(default="Belirtilmemiş", description="Yükün cinsi veya tipi")
    notes: Optional[str] = Field(default=None, description="Mailde geçen diğer kritik detaylar")

app = FastAPI(title="Minai AI Parser Service")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
@app.post("/parse-email/", response_model=LogisticsInquiry)
async def parse_email(email_content: str):
    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Sen uluslararası lojistik ve forwarder operasyonlarına hakim uzman bir yapay zeka asistansın. "
                        "Sana verilen düzensiz e-posta metninden yükleme limanı (POL), tahliye limanı (POD), "
                        "konteyner ekipman bilgisi (Volume) ve yük cinsini (Commodity) kesin olarak ayıkla."
                    )
                },
                {"role": "user", "content": email_content}
            ],
            response_format=LogisticsInquiry,
        )
        return response.choices[0].message.parsed
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))