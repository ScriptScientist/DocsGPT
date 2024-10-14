import redis
import time
import json
from application.core.settings import settings
from application.utils import get_hash


def make_redis():
    """
    Initialize a Redis client using the settings provided in the application settings.

    Returns:
        redis.Redis: A Redis client instance.
    """
    return redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
    )

def gen_cache_key(*messages, model="docgpt"):
    """
    Generate a unique cache key based on the latest user message and model.

    This function extracts the content of the latest user message from the `messages`
    list and combines it with the model name to generate a unique cache key using a hash function.
    This key can be used for caching responses in the system.

    Args:
        messages (list): A list of dictionaries representing the conversation messages.
                         Each dictionary should contain at least a 'content' field and a 'role' field.
        model (str, optional): The model name or identifier. Defaults to "docgpt".

    Raises:
        ValueError: I3messages are provided.
        ValueError: If `messages` is not a list.
        ValueError: If no user message is found in the conversation.

    Returns:
        str: A unique cache key generated by hashing the combined model name and latest user message.
    """
    if not all(isinstance(msg, dict) for msg in messages):
        raise ValueError("All messages must be dictionaries.")

    messages_str = json.dumps(list(messages), sort_keys=True)
    combined = f"{model}_{messages_str}"
    cache_key = get_hash(combined)
    return cache_key

def gen_cache(func):
    """
    Decorator to cache the response of a function that generates a response using an LLM.
    
    This decorator first checks if a response is cached for the given input (model and messages).
    If a cached response is found, it returns that. If not, it generates the response,
    caches it, and returns the generated response.
    Args:
        func (function): The function to be decorated.
    Returns:
        function: The wrapped function that handles caching and LLM response generation.
    """
    
    def wrapper(self, model, messages, *args, **kwargs):
        try:
            cache_key = gen_cache_key(*messages)
            redis_client = make_redis()
            cached_response = redis_client.get(cache_key)

            if cached_response:
                return cached_response.decode('utf-8')
            
            result = func(self, model, messages, *args, **kwargs)
            redis_client.set(cache_key, result, ex=3600)

            return result
        except ValueError as e:
            print(e)
            return "Error: No user message found in the conversation to generate a cache key."
    return wrapper

def stream_cache(func):
    """
    Decorator to cache the streamed response of an LLM function.
    
    This decorator first checks if a streamed response is cached for the given input (model and messages).
    If a cached response is found, it yields that. If not, it streams the response, caches it,
    and then yields the response.
    
    Args:
        func (function): The function to be decorated.
        
    Returns:
        function: The wrapped function that handles caching and streaming LLM responses.
        (self._raw_gen, decorators=decorators, model=model, messages=messages, stream=stream, *args, **kwargs
    """
    def wrapper(self, model, messages, stream, *args, **kwargs):
        cache_key = gen_cache_key(*messages)

        try:
            # we are using lrange and rpush to simulate streaming
            redis_client = make_redis()
            cached_response = redis_client.get(cache_key)
            if cached_response:
                print(f"Cache hit for stream key: {cache_key}")
                cached_response = json.loads(cached_response.decode('utf-8'))
                for chunk in cached_response:
                    yield chunk
                    # need to slow down the response to simulate streaming
                    # because the cached response is instantaneous
                    # and redis is using in-memory storage  
                    time.sleep(0.07)
                return

            result = func(self, model, messages, stream, *args, **kwargs)
            stream_cache_data = []
            
            for chunk in result:
                stream_cache_data.append(chunk)
                yield chunk 
            
            # expire the cache after 30 minutes
            redis_client.set(cache_key, json.dumps(stream_cache_data), ex=1800)
            print(f"Stream cache saved for key: {cache_key}")
        except ValueError as e:
            print(e)
            yield "Error: No user message found in the conversation to generate a cache key."
        
    return wrapper