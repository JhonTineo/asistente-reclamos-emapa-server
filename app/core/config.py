from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    opencode_go_api_key: str
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"
    llm_model: str = "deepseek-v4-flash"

    emapa_api_base_url: str = "https://comercial.emapasanmartin.com:8889/sysco-comercial/backend"
    emapa_access_token: str = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL3N5c2NvLmNvbS8iLCJzdWIiOiJ3d3cuc3lzY28uY29tIiwianRpIjoiQ0VTQVIiLCJ1c3VhcmlvIjoiQ0VTQVIiLCJhcGVsbGlkb3BhIjoiRkxPUkVTIiwiYXBlbGxpZG9tYSI6IlJJT1MiLCJjb2R1c3UiOiJDRVNBUiIsInBhc3N3b3JkIjoiTjJQRFVIcCtncnNWeXIwU1NPdXZqQT09IiwiY29kZW1wIjoiMDAxIiwiY29kc3VjIjoiMDAxIiwiY29kc2VkZSI6IjAwMSIsImVtcHJlc2EiOiJFUFMgRU1BUEEgU0FOIE1BUlRJTiBTLkEuIiwic3VjdXJzYWwiOiJUQVJBUE9UTyIsInNlZGVvcGVyYWNpb25hbCI6Ik9GSUNJTkEgVEFSQVBPVE8iLCJjb2RpbnNwZWN0b3IiOiIwMDAiLCJpcHNlcnZpZG9yIjoiU0hFK1QvV2ZSOXU5SE05azVWK3VMdz09Iiwibm9tYnJlX2JkIjoiNVZwdVdESk51MHBUOU83ZEI4cElIdz09IiwicHVlcnRvIjoiQlpZcHZ5UVFIaCtXN1BZbnZ4Z083dz09Iiwic3VjZGVmIjoiMCIsImV4cGlyYWNpb24iOiIxNzgxNTM3MDUyMTYxIiwidGlwb3VzdWFyaW8iOiIwMDEiLCJjb2RvZmljaW5hIjoiIiwiaWF0IjowLCJleHAiOjE3ODE1MzcwNTJ9.2So8TVkn0xQN2EnpLlDFp7KUY8CrHuRU3nxUktDTGVU"


settings = Settings()
