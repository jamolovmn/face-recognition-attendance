<?php

declare(strict_types=1);

namespace OCA\FaceAttendance\Controller;

use OCA\FaceAttendance\Db\EventMapper;
use OCA\FaceAttendance\Service\AttendanceService;
use OCP\AppFramework\Http;
use OCP\AppFramework\Http\Attribute\ApiRoute;
use OCP\AppFramework\Http\Attribute\NoAdminRequired;
use OCP\AppFramework\Http\DataResponse;
use OCP\AppFramework\OCSController;
use OCP\IRequest;
use OCP\IUserSession;

class ApiController extends OCSController {
	public function __construct(
		string $appName,
		IRequest $request,
		private AttendanceService $service,
		private EventMapper $mapper,
		private IUserSession $userSession,
	) {
		parent::__construct($appName, $request);
	}

	/** Called by the camera service for every confirmed arrival / stranger. */
	#[NoAdminRequired]
	#[ApiRoute(verb: 'POST', url: '/api/v1/events')]
	public function create(
		string $uid,
		string $camera,
		string $room,
		int $ts,
		?string $person = null,
		float $score = 0.0,
		?string $snapshot = null,
	): DataResponse {
		if (!$this->service->canAccess($this->userSession->getUser())) {
			return new DataResponse(['message' => 'forbidden'], Http::STATUS_FORBIDDEN);
		}
		if (!preg_match('/^[A-Za-z0-9_-]{8,64}$/', $uid)) {
			return new DataResponse(['message' => 'invalid uid'], Http::STATUS_BAD_REQUEST);
		}
		$person = $person !== null ? trim($person) : null;
		$event = $this->service->create(
			$uid,
			$person === null || $person === '' ? null : mb_substr($person, 0, 128),
			mb_substr($camera, 0, 64),
			mb_substr($room, 0, 128),
			$score,
			$ts,
			$snapshot,
		);
		return new DataResponse($event, Http::STATUS_CREATED);
	}

	/**
	 * @param string|null $person empty string = only unknown faces
	 */
	#[NoAdminRequired]
	#[ApiRoute(verb: 'GET', url: '/api/v1/events')]
	public function index(int $from, int $to, ?string $person = null, ?string $room = null, int $limit = 2000): DataResponse {
		if (!$this->service->canAccess($this->userSession->getUser())) {
			return new DataResponse(['message' => 'forbidden'], Http::STATUS_FORBIDDEN);
		}
		$limit = max(1, min($limit, 10000));
		return new DataResponse($this->mapper->findRange($from, $to, $person, $room, $limit));
	}

	/** Heartbeat of a camera node; tells it whether it should run the cameras. */
	#[NoAdminRequired]
	#[ApiRoute(verb: 'POST', url: '/api/v1/lease')]
	public function lease(string $node, int $priority = 1, int $ttl = 45): DataResponse {
		if (!$this->service->canAccess($this->userSession->getUser())) {
			return new DataResponse(['message' => 'forbidden'], Http::STATUS_FORBIDDEN);
		}
		if (!preg_match('/^[A-Za-z0-9_.-]{1,64}$/', $node)) {
			return new DataResponse(['message' => 'invalid node'], Http::STATUS_BAD_REQUEST);
		}
		return new DataResponse($this->service->lease($node, max(0, $priority), max(15, min($ttl, 600))));
	}
}
