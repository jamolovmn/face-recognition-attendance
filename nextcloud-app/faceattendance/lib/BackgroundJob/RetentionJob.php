<?php

declare(strict_types=1);

namespace OCA\FaceAttendance\BackgroundJob;

use OCA\FaceAttendance\Service\AttendanceService;
use OCP\AppFramework\Utility\ITimeFactory;
use OCP\BackgroundJob\TimedJob;
use Psr\Log\LoggerInterface;

class RetentionJob extends TimedJob {
	public function __construct(
		ITimeFactory $time,
		private AttendanceService $service,
		private LoggerInterface $logger,
	) {
		parent::__construct($time);
		$this->setInterval(24 * 3600);
	}

	protected function run($argument): void {
		$removed = $this->service->purgeOld();
		if ($removed > 0) {
			$this->logger->info("faceattendance: removed $removed events older than {$this->service->retentionDays()} days");
		}
	}
}
