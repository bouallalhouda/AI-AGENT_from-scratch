tools = [
    {
        "type": "function",
        "function": {
            "name": "validate_moroccan_phone",
            "description": "This function is used when the user enters his phone number, to verify that it is a valid Moroccan phone number so we can contact him later.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "The phone number the user provided, as a string of digits."
                    }
                },
                "required": ["phone_number"]
            }
        }
    }
]
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

user_message = "My phone number is 061234567823"

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": user_message}],
    tools=tools,
)

print(response)
import json
from main import validate_moroccan_phone  # reuse your real function

message = response.choices[0].message

if message.tool_calls:
    tool_call = message.tool_calls[0]  # the first (and only) tool request
    
    function_name = tool_call.function.name
    arguments = json.loads(tool_call.function.arguments)  # string → real dict
    
    print(f"\nLLM wants to call: {function_name}")
    print(f"With arguments: {arguments}")
    
    if function_name == "validate_moroccan_phone":
        phone_number = arguments["phone_number"]
        result = validate_moroccan_phone(phone_number)
        print(f"\nActual validation result: {result}")
        second_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": user_message},
                message,  # the LLM's own "I want to call this tool" message
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,  # matches this answer to that question
                    "content": str(result),
                }
            ]
        )
        
        print(f"\nFinal answer from LLM: {second_response.choices[0].message.content}")