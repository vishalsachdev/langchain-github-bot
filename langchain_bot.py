from langchain.llms import OpenAI
from langchain.chains.qa_with_sources import load_qa_with_sources_chain
from langchain.docstore.document import Document
import requests
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.vectorstores.faiss import FAISS
from langchain.text_splitter import CharacterTextSplitter
import pathlib
import subprocess
import tempfile
from dagster import asset
from dagster import FreshnessPolicy, RetryPolicy
import pickle
import gradio as gr
import re
import os

os.environ["OPENAI_API_KEY"] = "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"

def get_github_docs(repo_owner, repo_name):
    with tempfile.TemporaryDirectory() as d:
        subprocess.check_call(
            f"git clone --depth 1 https://github.com/{repo_owner}/{repo_name}.git .",
            cwd=d,
            shell=True,
        )
        git_sha = (
            subprocess.check_output("git rev-parse HEAD", shell=True, cwd=d)
            .decode("utf-8")
            .strip()
        )
        repo_path = pathlib.Path(d)
        markdown_files = list(repo_path.glob("**/*.md")) + list(
            repo_path.glob("**/*.mdx")
        )
        for markdown_file in markdown_files:
            with open(markdown_file, "r") as f:
                relative_path = markdown_file.relative_to(repo_path)
                github_url = f"https://github.com/{repo_owner}/{repo_name}/blob/{git_sha}/{relative_path}"
                yield Document(page_content=f.read(), metadata={"source": github_url})

username = ""
repo_name = ""
url = ""
def get_url(url):
    match = re.match(r'https://github.com/([\w-]+)/([\w-]+)', url)
    username = match.group(1)
    repo_name = match.group(2)
    return repo_name, username

@asset
def source_docs():
    return list(get_github_docs(get_url(url)))


@asset(
    retry_policy=RetryPolicy(max_retries=5, delay=5),
    freshness_policy=FreshnessPolicy(maximum_lag_minutes=60 * 24),
)
def search_index(source_docs):
    source_chunks = []
    splitter = CharacterTextSplitter(separator=" ", chunk_size=1024, chunk_overlap=0)
    for source in source_docs:
        for chunk in splitter.split_text(source.page_content):
            source_chunks.append(Document(page_content=chunk, metadata=source.metadata))

    with open("search_index.pickle", "wb") as f:
        pickle.dump(FAISS.from_documents(source_chunks, OpenAIEmbeddings()), f)


chain = load_qa_with_sources_chain(OpenAI(temperature=0))

def print_answer(question):
    with open("search_index.pickle", "rb") as f:
        search_index = pickle.load(f)
    return chain(
        {
            "input_documents": search_index.similarity_search(question, k=4),
            "question": question,
        },
        return_only_outputs=True,
        )

url = gr.Interface(
    fn= get_url,
    inputs=gr.Textbox(lines=2, placeholder="Enter your URL here...", label="url"),
    outputs= "text"
)
q_and_a = gr.Interface(
    fn=print_answer,
    inputs=gr.Textbox(lines=2, placeholder="Enter your question here...", label="user_question"),
    outputs="text",
)

demo = gr.TabbedInterface([url, q_and_a], ["Enter URL", "ChatBot"])
demo.launch(share=True)

