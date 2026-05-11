"""
RAG Agent - Retrieval Augmented Generation with 2-hop retrieval.

Performs:
1. First retrieval: get initial relevant chunks
2. Analyze gaps: identify what information is missing
3. Second retrieval: targeted retrieval for gaps
4. Synthesize: combine chunks into findings
"""

import logging
import json
import uuid
from typing import Optional, List
from api.context.schema import (
    AgentContext, Chunk, AgentOutput
)
from api.context.budget import ContextBudgetManager
from api.llm import build_openrouter_llm
from langchain_openai import ChatOpenAI
import os

logger = logging.getLogger(__name__)

class RAGAgent:
    """
    Retrieval Augmented Generation agent.
    
    Implements 2-hop retrieval strategy:
    1. Initial retrieval based on query
    2. Gap analysis to identify missing info
    3. Targeted second retrieval
    4. Chunk synthesis
    
    Uses ChromaDB for vector storage.
    """
    
    def __init__(self):
        """Initialize the RAG agent."""
        self.name = "rag"
        self.budget_tokens = 3000
        self._init_llm()
        self._init_vector_store()
    
    def _init_llm(self):
        """Initialize LLM client."""
        self.client = build_openrouter_llm(3000)
        if self.client is not None:
            return

        from openai import OpenAI
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    def _init_vector_store(self):
        """Initialize ChromaDB vector store with sample data."""
        try:
            import chromadb
            from chromadb.config import Settings
            
            # Create persistent client
            settings = Settings(
                chroma_db_impl="duckdb+parquet",
                persist_directory=os.getenv("CHROMA_PATH", "./chroma_data"),
                anonymized_telemetry=False,
            )
            
            self.chroma_client = chromadb.Client(settings)
            
            
            self.collection = self.chroma_client.get_or_create_collection(
                name="mega_ai_docs",
                metadata={"hnsw:space": "cosine"}
            )
            
            if self.collection.count() == 0:
                self._seed_sample_data()
            
            logger.info("ChromaDB vector store initialized")
        
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {str(e)}")
            self.collection = None
    
    def _seed_sample_data(self):
        """Seed ChromaDB with sample documents."""
        documents = [
            "Artificial Intelligence (AI) is the simulation of human intelligence by machines.",
            "Machine Learning is a subset of AI that focuses on learning from data.",
            "Deep Learning uses neural networks with multiple layers.",
            "Natural Language Processing enables computers to understand human language.",
            "Computer Vision allows machines to interpret visual information.",
            "Reinforcement Learning trains agents through reward signals.",
            "Transfer Learning reuses models trained on one task for another.",
            "Supervised Learning requires labeled training data.",
            "Unsupervised Learning discovers patterns in unlabeled data.",
            "Neural Networks are inspired by biological brain structures.",
            "Transformers have revolutionized NLP with attention mechanisms.",
            "GPT models generate human-like text based on prompts.",
            "BERT models understand bidirectional context in language.",
            "Computer Science is the study of computation and algorithms.",
            "Data Science combines statistics, programming, and domain expertise.",
            "Big Data involves processing large volumes of diverse data.",
            "Cloud Computing provides on-demand computing resources.",
            "Cybersecurity protects systems from unauthorized access.",
            "Blockchain enables decentralized and secure transactions.",
            "Quantum Computing harnesses quantum mechanics for computation.",
        ]
        
        # Create embeddings (mock for demo)
        metadatas = [{"source": f"doc_{i}"} for i in range(len(documents))]
        ids = [str(uuid.uuid4()) for _ in range(len(documents))]
        
        self.collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        
        logger.info(f"Seeded ChromaDB with {len(documents)} sample documents")
    
    async def execute(
        self,
        context: AgentContext,
        budget_manager: ContextBudgetManager
    ) -> AgentContext:
        """
        Execute the RAG agent with 2-hop retrieval.
        
        Args:
            context: The shared agent context
            budget_manager: Budget manager for token tracking
            
        Returns:
            Updated context with retrieved_chunks populated
        """
        import time
        
        start_time = time.time()
        
        # Check budget
        remaining = budget_manager.check_remaining(self.name)
        if remaining <= 0:
            logger.error(f"RAG agent: budget exhausted")
            return context
        
        try:
            budget_manager.declare_budget(self.name, self.budget_tokens)
            
            logger.info(
                f"RAG agent starting for job {context.job_id}",
                extra={"job_id": str(context.job_id), "query": context.query}
            )
            
            total_tokens = 0
            
            # === HOP 1: Initial retrieval ===
            logger.debug("RAG Hop 1: Initial retrieval")
            context.retrieval_iteration = 1
            
            await context.emit_event("TOOL_CALL", {
                "tool_name": "chroma.retrieve_hop1",
                "tool_input": {"query": context.query, "k": 5}
            }, agent_id=self.name)
            chunks_hop1 = await self._retrieve_chunks(context.query, k=5)
            await context.emit_event("TOOL_RESULT", {
                "tool_name": "chroma.retrieve_hop1",
                "tool_output": {"chunks_found": len(chunks_hop1)}
            }, agent_id=self.name)
            context.retrieved_chunks.extend(chunks_hop1)
            tokens_hop1 = self._estimate_tokens(context.query + str(chunks_hop1))
            total_tokens += tokens_hop1
            
            logger.debug(
                f"Hop 1 retrieved {len(chunks_hop1)} chunks",
                extra={"chunk_count": len(chunks_hop1)}
            )
            
            # === Gap Analysis ===
            logger.debug("RAG Gap Analysis")
            await context.emit_event("TOOL_CALL", {
                "tool_name": "llm.gap_analysis",
                "tool_input": {"query": context.query, "chunk_count": len(chunks_hop1)}
            }, agent_id=self.name)
            gap_analysis = await self._analyze_gaps(context.query, chunks_hop1)
            await context.emit_event("TOOL_RESULT", {
                "tool_name": "llm.gap_analysis",
                "tool_output": {"gaps": gap_analysis.get("gaps", []), "refined_queries": gap_analysis.get("refined_queries", [])}
            }, agent_id=self.name)
            tokens_gap = self._estimate_tokens(gap_analysis)
            total_tokens += tokens_gap
            
            logger.debug(
                "Gap analysis complete",
                extra={"gaps_identified": len(gap_analysis.get("gaps", []))}
            )
            
            # === HOP 2: Targeted retrieval based on gaps ===
            if gap_analysis.get("gaps"):
                logger.debug("RAG Hop 2: Targeted retrieval")
                context.retrieval_iteration = 2
                
                gap_queries = gap_analysis.get("refined_queries", [context.query])
                
                for gap_query in gap_queries[:2]:  # Limit to 2 additional queries
                    await context.emit_event("TOOL_CALL", {
                        "tool_name": "chroma.retrieve_hop2",
                        "tool_input": {"query": gap_query, "k": 3}
                    }, agent_id=self.name)
                    chunks_gap = await self._retrieve_chunks(gap_query, k=3)
                    await context.emit_event("TOOL_RESULT", {
                        "tool_name": "chroma.retrieve_hop2",
                        "tool_output": {"gap_query": gap_query, "chunks_found": len(chunks_gap)}
                    }, agent_id=self.name)
                    
                    # Avoid duplicates
                    existing_ids = {c.id for c in context.retrieved_chunks}
                    new_chunks = [c for c in chunks_gap if c.id not in existing_ids]
                    
                    context.retrieved_chunks.extend(new_chunks)
                    tokens_gap_retrieval = self._estimate_tokens(gap_query + str(new_chunks))
                    total_tokens += tokens_gap_retrieval
                    
                    logger.debug(
                        f"Hop 2 retrieved {len(new_chunks)} new chunks from gap query",
                        extra={"gap_query_count": len(gap_queries), "new_chunks": len(new_chunks)}
                    )
            
            # === Synthesis ===
            logger.debug("RAG Synthesis: combining chunks")
            await context.emit_event("TOOL_CALL", {
                "tool_name": "llm.rag_synthesis",
                "tool_input": {"query": context.query, "retrieved_chunk_count": len(context.retrieved_chunks)}
            }, agent_id=self.name)
            synthesis = await self._synthesize_chunks(context.query, context.retrieved_chunks)
            await context.emit_event("TOOL_RESULT", {
                "tool_name": "llm.rag_synthesis",
                "tool_output": {"response_preview": synthesis[:500], "chars": len(synthesis)}
            }, agent_id=self.name)
            tokens_synthesis = self._estimate_tokens(synthesis)
            total_tokens += tokens_synthesis
            
            # Consume tokens
            budget_manager.consume(self.name, total_tokens, context)
            
            # Record output
            latency_ms = (time.time() - start_time) * 1000
            context.agent_outputs[self.name] = AgentOutput(
                agent_name=self.name,
                result=synthesis,
                tokens_used=total_tokens,
                tool_calls_made=3,  # 2 retrievals + synthesis
                confidence=0.85
            )
            
            logger.info(
                f"RAG agent completed: {len(context.retrieved_chunks)} chunks retrieved",
                extra={
                    "job_id": str(context.job_id),
                    "chunk_count": len(context.retrieved_chunks),
                    "retrieval_hops": context.retrieval_iteration,
                    "latency_ms": latency_ms,
                    "tokens_used": total_tokens
                }
            )
            
            return context
        
        except Exception as e:
            logger.error(
                f"RAG agent failed: {str(e)}",
                extra={"job_id": str(context.job_id), "error": str(e)}
            )
            return context
    
    async def _retrieve_chunks(self, query: str, k: int = 5) -> List[Chunk]:
        """
        Retrieve chunks from vector store.
        
        Args:
            query: Query string
            k: Number of chunks to retrieve
            
        Returns:
            List of Chunk objects
        """
        try:
            if not self.collection:
                logger.warning("ChromaDB not initialized, returning empty results")
                return []
            
            # Query the collection
            results = self.collection.query(
                query_texts=[query],
                n_results=k
            )
            
            chunks = []
            
            if results and results.get("documents"):
                for i, doc in enumerate(results["documents"][0]):
                    # Extract distance (convert to relevance score 0-1)
                    distance = results["distances"][0][i] if results.get("distances") else 0
                    relevance_score = max(0, 1 - distance)  # Convert distance to score
                    
                    chunk = Chunk(
                        id=results["ids"][0][i] if results.get("ids") else str(uuid.uuid4()),
                        content=doc,
                        source_url="chromadb://sample",
                        relevance_score=relevance_score,
                        metadata=results["metadatas"][0][i] if results.get("metadatas") else {}
                    )
                    chunks.append(chunk)
            
            return chunks
        
        except Exception as e:
            logger.error(f"Failed to retrieve chunks: {str(e)}")
            return []
    
    async def _analyze_gaps(self, query: str, chunks: List[Chunk]) -> dict:
        """
        Analyze gaps in retrieved information.
        
        Args:
            query: Original query
            chunks: Retrieved chunks
            
        Returns:
            Gap analysis with refined queries
        """
        try:
            chunk_text = "\n".join([c.content for c in chunks])
            
            prompt = f"""Analyze the following retrieved chunks for the query and identify gaps.

Query: {query}

Retrieved Information:
{chunk_text}

What information is missing or incomplete? Suggest 1-2 refined search queries to find the missing info.

Return JSON:
{{
    "gaps": ["gap1", "gap2"],
    "refined_queries": ["query1", "query2"]
}}"""
            
            if isinstance(self.client, ChatOpenAI):
                response = self.client.invoke(prompt).content
                return json.loads(response)

            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                max_tokens=500,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}]
            )
            response = response.choices[0].message.content
            
            return json.loads(response)
        
        except Exception as e:
            logger.error(f"Gap analysis failed: {str(e)}")
            return {"gaps": [], "refined_queries": []}
    
    async def _synthesize_chunks(self, query: str, chunks: List[Chunk]) -> str:
        """
        Synthesize chunks into coherent findings.
        
        Args:
            query: Original query
            chunks: Retrieved chunks
            
        Returns:
            Synthesized findings
        """
        try:
            chunk_text = "\n".join(
                [f"[{i}] {c.content} (relevance: {c.relevance_score:.2f})"
                 for i, c in enumerate(chunks)]
            )
            
            prompt = f"""Synthesize the following information to answer the query.

Query: {query}

Retrieved Information:
{chunk_text}

Create a comprehensive answer that:
1. Answers the query using the information
2. Cites which chunks were used
3. Identifies any gaps or uncertainties

Return as plain text (not JSON)."""
            
            if isinstance(self.client, ChatOpenAI):
                return self.client.invoke(prompt).content

            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content
        
        except Exception as e:
            logger.error(f"Chunk synthesis failed: {str(e)}")
            return "Failed to synthesize information"
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate tokens."""
        return max(1, len(str(text)) // 4)
