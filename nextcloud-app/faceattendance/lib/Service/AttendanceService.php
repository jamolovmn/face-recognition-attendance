<?php

declare(strict_types=1);

namespace OCA\FaceAttendance\Service;

use OCA\FaceAttendance\AppInfo\Application;
use OCA\FaceAttendance\Db\Event;
use OCA\FaceAttendance\Db\EventMapper;
use OCP\Files\IAppData;
use OCP\Files\NotFoundException;
use OCP\Files\SimpleFS\ISimpleFile;
use OCP\IAppConfig;
use OCP\IGroupManager;
use OCP\IUser;
use Psr\Log\LoggerInterface;

class AttendanceService {
	public const GROUP = 'attendance';
	private const MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024;
	/** A person seen in the same room again within this window is the same arrival (failover overlap, retries). */
	private const DUPLICATE_WINDOW_SEC = 120;

	public function __construct(
		private EventMapper $mapper,
		private IAppData $appData,
		private IGroupManager $groupManager,
		private IAppConfig $appConfig,
		private LoggerInterface $logger,
	) {
	}

	/** Attendance is personal data: only admins and the "attendance" group may see or write it. */
	public function canAccess(?IUser $user): bool {
		if ($user === null) {
			return false;
		}
		$uid = $user->getUID();
		return $this->groupManager->isAdmin($uid) || $this->groupManager->isInGroup($uid, self::GROUP);
	}

	public function create(string $uid, ?string $person, string $camera, string $room, float $score, int $ts, ?string $snapshotB64): Event {
		$existing = $this->mapper->findByUid($uid);
		if ($existing !== null) {
			return $existing; // the camera service retries - make it idempotent
		}
		if ($person !== null) {
			$recent = $this->mapper->findNear($person, $room, $ts, self::DUPLICATE_WINDOW_SEC);
			if ($recent !== null) {
				return $recent; // two camera nodes briefly running at once during a failover
			}
		}

		$event = new Event();
		$event->setUid($uid);
		$event->setPerson($person);
		$event->setCamera($camera);
		$event->setRoom($room);
		$event->setScore($score);
		$event->setTs($ts);

		if ($snapshotB64 !== null && $snapshotB64 !== '') {
			$bytes = base64_decode($snapshotB64, true);
			if ($bytes !== false && strlen($bytes) <= self::MAX_SNAPSHOT_BYTES && str_starts_with($bytes, "\xFF\xD8")) {
				try {
					$folderName = gmdate('Y-m-d', $ts);
					$folder = $this->snapshotRoot()->getFolder($folderName);
				} catch (NotFoundException) {
					$folder = $this->snapshotRoot()->newFolder($folderName);
				}
				$folder->newFile($uid . '.jpg', $bytes);
				$event->setSnapshot($folderName . '/' . $uid . '.jpg');
			} else {
				$this->logger->warning('faceattendance: invalid snapshot ignored for event ' . $uid);
			}
		}

		return $this->mapper->insert($event);
	}

	public function snapshot(int $id): ISimpleFile {
		$event = $this->mapper->find($id);
		$path = $event->getSnapshot();
		if ($path === null) {
			throw new NotFoundException();
		}
		[$folder, $file] = explode('/', $path, 2);
		return $this->snapshotRoot()->getFolder($folder)->getFile($file);
	}

	public function retentionDays(): int {
		return $this->appConfig->getValueInt(Application::APP_ID, 'retention_days', 90);
	}

	/** Delete events and snapshots older than the retention period. Returns number removed. */
	public function purgeOld(): int {
		$days = $this->retentionDays();
		if ($days <= 0) {
			return 0;
		}
		$cutoff = time() - $days * 86400;
		$removed = 0;
		while ($events = $this->mapper->findOlderThan($cutoff)) {
			foreach ($events as $event) {
				$this->deleteSnapshot($event);
				$this->mapper->delete($event);
				$removed++;
			}
		}
		// Day folders are empty now - drop them.
		foreach ($this->snapshotRoot()->getDirectoryListing() as $folder) {
			if ($folder->getName() < gmdate('Y-m-d', $cutoff) && $folder->getDirectoryListing() === []) {
				$folder->delete();
			}
		}
		return $removed;
	}

	private function deleteSnapshot(Event $event): void {
		$path = $event->getSnapshot();
		if ($path === null) {
			return;
		}
		try {
			[$folder, $file] = explode('/', $path, 2);
			$this->snapshotRoot()->getFolder($folder)->getFile($file)->delete();
		} catch (NotFoundException) {
		}
	}

	private function snapshotRoot(): \OCP\Files\SimpleFS\ISimpleFolder {
		try {
			return $this->appData->getFolder('snapshots');
		} catch (NotFoundException) {
			return $this->appData->newFolder('snapshots');
		}
	}

	/**
	 * Active/standby failover between several camera nodes: only the lease holder
	 * runs the cameras. A node with a lower priority number takes the lease over
	 * at once; others get it only after the holder stopped renewing it.
	 *
	 * @return array{leader: bool, holder: string, until: int}
	 */
	public function lease(string $node, int $priority, int $ttl): array {
		$now = time();
		$holder = $this->appConfig->getValueString(Application::APP_ID, 'lease_node', '', lazy: true);
		$holderPriority = $this->appConfig->getValueInt(Application::APP_ID, 'lease_priority', PHP_INT_MAX, lazy: true);
		$until = $this->appConfig->getValueInt(Application::APP_ID, 'lease_until', 0, lazy: true);

		if ($holder === '' || $holder === $node || $until < $now || $priority < $holderPriority) {
			if ($holder !== $node) {
				$this->logger->info("faceattendance: camera node '$node' became active (was '$holder')");
			}
			$holder = $node;
			$until = $now + $ttl;
			$this->appConfig->setValueString(Application::APP_ID, 'lease_node', $node, lazy: true);
			$this->appConfig->setValueInt(Application::APP_ID, 'lease_priority', $priority, lazy: true);
			$this->appConfig->setValueInt(Application::APP_ID, 'lease_until', $until, lazy: true);
		}
		return ['leader' => $holder === $node, 'holder' => $holder, 'until' => $until];
	}
}
