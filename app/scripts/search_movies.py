import sys
import os

# Add the current directory's parent (app/) to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chroma_utils import search_movies

def main():
    query = "1990s Chemical burn on hand, man with no name, self inflicted burn injury"
    print(f"Searching for: {query}")
    found = search_movies(query, n_results=5)
    print(f"Found {len(found)} movies:")

    for idx, item in enumerate(found, start=1):
        print(f"{idx}. {item['title']} | distance={item['distance']}")
        print(item["document"])
        print("-" * 80)

if __name__ == "__main__":
    main()