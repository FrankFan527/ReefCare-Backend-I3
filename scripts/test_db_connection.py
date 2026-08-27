# import asyncio
# import selectors
# import sys

# from sqlalchemy import text

# from app.db.session import AsyncSessionLocal


# async def test_database():
#     async with AsyncSessionLocal() as db:
#         result = await db.execute( 
#             text(
#                 """
#                 SELECT
#                     report_id,
#                     report_reference,
#                     submitted_at
#                 FROM report
#                 WHERE deleted_at IS NULL
#                 ORDER BY report_id
#                 LIMIT 5
#                 """
#             )
#         )

#         rows = result.mappings().all()

#         print("Reports:")

#         for row in rows:
#             print(dict(row))


# if __name__ == "__main__":
#     if sys.platform == "win32":
#         loop = asyncio.SelectorEventLoop(
#             selectors.SelectSelector()
#         )
#         asyncio.set_event_loop(loop)

#         try:
#             loop.run_until_complete(test_database())
#         finally:
#             loop.close()
#     else:
#         asyncio.run(test_database())