import os
import time
import asyncio

import logging
logger = logging.getLogger("__main__")

class Recorder:
    def __init__(self, recording_path, processed_path, refresh_rate=15, ffmpeg_path="ffmpeg", use_rclone=False, **kwargs):
        self.refresh_rate = int(refresh_rate)
        self.ffmpeg_path = ffmpeg_path
        self.recording_path = recording_path
        self.processed_path = processed_path
        self.streamlink_options = []
        self.cleanup_queue = asyncio.Queue()
        self.cleanup_task = asyncio.create_task(self.cleanup())

    async def cleanup(self):
        logger.debug("Creating cleanup task.")
        while True:
            user_recording_path, user_processed_path, username = await self.cleanup_queue.get()
            video_list = [filename for filename in os.listdir(user_recording_path) if os.path.isfile(os.path.join(user_recording_path, filename))]
            for filename in video_list:
                recorded_filename = os.path.join(user_recording_path, filename)
                processed_export_filename = os.path.join(user_processed_path, filename)
                logger.debug(f"Fixing {recorded_filename}.")
                command = [self.ffmpeg_path, '-nostdin', '-y', '-err_detect', 'ignore_err', '-i', recorded_filename, '-c', 'copy', processed_export_filename]
                process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await process.wait()

                if process.returncode == 0:
                    await asyncio.sleep(30) #Bug
                    try:
                        os.remove(recorded_filename)
                    except Exception as e:
                        logger.error(f"error removing the file at {recorded_filename} with \n{e}")          
                else:
                    logger.error(f"ffmpeg returned error code {process.returncode}")
        logger.debug("Cleanup task completed")

    async def record(self, username, url, check_stream_function):
        """ Start recording for specified url """
        try:
            recording_path = os.path.join(self.recording_path, username)
            processed_path = os.path.join(self.processed_path, username)

            if not os.path.isdir(recording_path):
                os.makedirs(recording_path)
            if not os.path.isdir(processed_path):
                os.makedirs(processed_path)

            # await self.cleanup_queue.put((recording_path, processed_path, username))

            should_hold = False # debug feature, might become new feature
            continue_hold = True

            while True:
                status, title = await check_stream_function(username)
                if status:
                    if should_hold and continue_hold:
                        if isinstance(self.refresh_rate, int): #dont choke the event loop
                            await asyncio.sleep(self.refresh_rate)
                        continue

                    logger.info(f"{username} has started streaming.")

                    filename = username + " - " + str(int(time.time())) + " - " + title + ".mp4"
                    filename = "".join(x for x in filename if x.isalnum() or x in [" ", "-", "_", "."])
                    recorded_filename = os.path.join(recording_path, filename)

                    command = ["streamlink", url, "best", "-o", recorded_filename]
                    command.extend(self.streamlink_options)
                
                    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                    await process.wait()

                    if process.returncode == 0 and os.path.exists(recorded_filename) and os.path.isfile(recorded_filename):
                        logger.info(f"{username} has finished recording.")
                        await self.cleanup_queue.put((recording_path, processed_path, username))
                    else:
                        logger.info(f"{username} is not streaming.")
                else:
                    continue_hold = False

                if isinstance(self.refresh_rate, int):
                        await asyncio.sleep(self.refresh_rate)

        except asyncio.CancelledError:
            logger.info(f"{username} has been removed from the watch pool.")

