"""LLM interaction wrapper"""
import re
from langchain.chat_models import init_chat_model


class LLMClient:
    def __init__(self, model: str, provider: str):
        self.model = model
        self.provider = provider
        self.client = init_chat_model(model=model, model_provider=provider)
    
    def invoke(self, prompt: str) -> str:
        """Send prompt and get response"""
        response = self.client.invoke(prompt)
        return response.content
    
    def extract_code_from_response(self, text: str) -> str:
        """Extract code from markdown blocks"""
        code_match = re.search(r'```python\n(.*?)```', text, re.DOTALL)
        if code_match:
            extracted = code_match.group(1)
            print(f"   Extracted code from markdown block ({len(extracted)} chars)")
            # Convert // comments to # for Python
            extracted = extracted.replace("// MUTANT", "# MUTANT")
            return extracted
        else:
            print("   No markdown code block found, returning raw response")
            # Convert // comments to # for Python
            return text.replace("// MUTANT", "# MUTANT")

    def extract_json_from_response(self, text: str) -> str:
        """Extract JSON from markdown blocks or raw response"""
        # Try to find JSON in markdown code block (```json or ````)
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            print(f"   Extracted JSON from markdown block")
            return json_match.group(1)

        # Try to find raw JSON (just the braces and content)
        json_match = re.search(r'(\{.*\})', text, re.DOTALL)
        if json_match:
            print(f"   Extracted raw JSON from response")
            return json_match.group(1)

        # Return original text if no JSON found
        print("   No JSON found, returning raw response")
        return text