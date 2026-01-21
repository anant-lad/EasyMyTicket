"""
Web Search Service
Provides internet search capabilities for deep analysis of technical queries
Supports DuckDuckGo search (free, no API key required)
"""
from typing import List, Dict, Any, Optional
import traceback


class WebSearchService:
    """
    Provides web search capabilities for deep analysis
    Currently supports DuckDuckGo (can be extended to Tavily, SerpAPI)
    """
    
    def __init__(self, provider: str = 'duckduckgo', cache_duration: int = 3600):
        """
        Initialize web search service
        
        Args:
            provider: Search provider ('duckduckgo', 'tavily', 'serpapi')
            cache_duration: Cache duration in seconds (default: 1 hour)
        """
        self.provider = provider
        self.cache_duration = cache_duration
        self._cache = {}
        self._lazy_imports = {}
    
    def _import_duckduckgo(self):
        """Lazy import DuckDuckGo search library"""
        if 'ddg' not in self._lazy_imports:
            try:
                from duckduckgo_search import DDGS
                self._lazy_imports['ddg'] = DDGS
            except ImportError:
                print("Warning: duckduckgo-search not installed")
                print("Install with: pip install duckduckgo-search")
                self._lazy_imports['ddg'] = None
    
    def search(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """
        Search the web and return results
        
        Args:
            query: Search query
            num_results: Number of results to return (default: 5)
        
        Returns:
            List of dictionaries with 'title', 'snippet', 'url' keys
        """
        # Check cache first
        cache_key = f"{query}:{num_results}"
        if cache_key in self._cache:
            cached_time, cached_results = self._cache[cache_key]
            import time
            if time.time() - cached_time < self.cache_duration:
                print(f"🔍 Using cached search results for: {query}")
                return cached_results
        
        results = []
        
        try:
            if self.provider == 'duckduckgo':
                results = self._search_duckduckgo(query, num_results)
            else:
                print(f"Unsupported search provider: {self.provider}")
                return []
            
            # Cache results
            import time
            self._cache[cache_key] = (time.time(), results)
            
            return results
            
        except Exception as e:
            print(f"Error performing web search: {e}")
            traceback.print_exc()
            return []
    
    def _search_duckduckgo(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Perform DuckDuckGo search"""
        self._import_duckduckgo()
        
        if 'ddg' not in self._lazy_imports or not self._lazy_imports['ddg']:
            print("DuckDuckGo search library not available")
            return []
        
        try:
            DDGS = self._lazy_imports['ddg']
            
            print(f"🔍 Searching DuckDuckGo for: {query}")
            
            with DDGS() as ddgs:
                search_results = list(ddgs.text(query, max_results=num_results))
            
            results = []
            for result in search_results:
                results.append({
                    'title': result.get('title', ''),
                    'snippet': result.get('body', ''),
                    'url': result.get('href', '')
                })
            
            print(f"✅ Found {len(results)} search results")
            return results
            
        except Exception as e:
            print(f"Error in DuckDuckGo search: {e}")
            traceback.print_exc()
            return []
    
    def search_and_summarize(self, query: str, llm_client, num_results: int = 5) -> str:
        """
        Search web and use LLM to summarize findings
        
        Args:
            query: Search query
            llm_client: LLM client with call_cortex_llm method
            num_results: Number of results to search
        
        Returns:
            Summarized findings from web search
        """
        try:
            # Perform search
            results = self.search(query, num_results)
            
            if not results:
                return "No web search results found."
            
            # Build context from search results
            context = "Web Search Results:\\n\\n"
            for i, result in enumerate(results, 1):
                context += f"{i}. {result['title']}\\n"
                context += f"   {result['snippet']}\\n"
                context += f"   Source: {result['url']}\\n\\n"
            
            # Use LLM to summarize
            prompt = f"""Based on the following web search results, provide a concise summary of the key information related to the query: "{query}"

{context}

Provide a clear, actionable summary that synthesizes the information from these sources."""
            
            summary = llm_client.call_cortex_llm(prompt, json_response=False)
            
            return summary if summary else "Unable to summarize search results."
            
        except Exception as e:
            print(f"Error in search and summarize: {e}")
            return f"Error summarizing search results: {str(e)}"


# Singleton instance
_web_search_service = None

def get_web_search_service(provider: str = 'duckduckgo') -> WebSearchService:
    """Get or create web search service instance"""
    global _web_search_service
    if _web_search_service is None:
        _web_search_service = WebSearchService(provider)
    return _web_search_service
